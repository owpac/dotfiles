"""Lint engine: rule loading, dispatch, and types."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from .config import get_host_dir

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
_VALID_SEVERITIES = {SEVERITY_ERROR, SEVERITY_WARNING}

_BUILTIN_TYPE_PREFIX = "kompose.rules._builtin"
_HANDLER_PACKAGE = "kompose.rules"


@dataclass
class Issue:
    message: str
    location: str = ""
    fix: str = ""


@dataclass
class LintContext:
    service_name: str
    compose_path: Path
    content: str
    parsed: dict
    globals: dict


@dataclass
class RuleSpec:
    name: str
    category: str
    severity: str = SEVERITY_ERROR
    type: str | None = None
    handler: str | None = None
    exclude: list = field(default_factory=list)
    params: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"Rule '{self.name}': invalid severity '{self.severity}' "
                f"(expected one of: {sorted(_VALID_SEVERITIES)})"
            )
        if bool(self.type) == bool(self.handler):
            raise ValueError(
                f"Rule '{self.name}': must have exactly one of `type:` or `handler:`"
            )


@dataclass
class RuleResult:
    rule: RuleSpec
    issues: list[Issue]


@dataclass
class ServiceLintResult:
    service_name: str
    rule_results: list[RuleResult] = field(default_factory=list)

    def issues_in_category(self, category: str) -> list[Issue]:
        return [
            issue
            for rr in self.rule_results
            if rr.rule.category == category
            for issue in rr.issues
        ]

    @property
    def has_errors(self) -> bool:
        return any(
            rr.issues and rr.rule.severity == SEVERITY_ERROR for rr in self.rule_results
        )

    @property
    def error_count(self) -> int:
        return sum(
            len(rr.issues)
            for rr in self.rule_results
            if rr.rule.severity == SEVERITY_ERROR
        )

    @property
    def warning_count(self) -> int:
        return sum(
            len(rr.issues)
            for rr in self.rule_results
            if rr.rule.severity == SEVERITY_WARNING
        )


def get_kompose_dir(host: str | None = None) -> Path:
    return get_host_dir(host) / ".kompose"


def _load_yaml_file(path: Path) -> dict:
    content = path.read_text()
    data = yaml.safe_load(content) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping at top level")
    return data


def _parse_rules_block(block: list, source: Path) -> list[RuleSpec]:
    if not isinstance(block, list):
        raise ValueError(f"{source}: `rules:` must be a list")
    specs = []
    for entry in block:
        if not isinstance(entry, dict):
            raise ValueError(f"{source}: each rule must be a mapping")
        spec = RuleSpec(
            name=entry["name"],
            category=entry["category"],
            severity=entry.get("severity", SEVERITY_ERROR),
            type=entry.get("type"),
            handler=entry.get("handler"),
            exclude=entry.get("exclude") or [],
            params=entry.get("params") or {},
        )
        specs.append(spec)
    return specs


def load_rules(host: str | None = None) -> tuple[dict, list[RuleSpec]]:
    """Load globals + rules from .kompose/ in the host directory.

    Supports two layouts (can coexist):
      - mono-file: .kompose/rules.yaml (contains `globals:` and `rules:`)
      - multi-file: .kompose/globals.yaml + .kompose/rules/*.yaml

    Rules from both sources are merged by name; duplicates raise an error.
    """
    kompose_dir = get_kompose_dir(host)
    if not kompose_dir.exists():
        raise FileNotFoundError(
            f"Missing kompose config directory: {kompose_dir}\n"
            f"Create a rules.yaml (see README)."
        )

    globals_dict: dict = {}
    specs_by_name: dict[str, tuple[RuleSpec, Path]] = {}

    mono = kompose_dir / "rules.yaml"
    if mono.exists():
        data = _load_yaml_file(mono)
        globals_dict.update(data.get("globals") or {})
        for spec in _parse_rules_block(data.get("rules") or [], mono):
            specs_by_name[spec.name] = (spec, mono)

    globals_file = kompose_dir / "globals.yaml"
    if globals_file.exists():
        data = _load_yaml_file(globals_file)
        globals_dict.update(data.get("globals") or data)

    rules_dir = kompose_dir / "rules"
    if rules_dir.is_dir():
        for path in sorted(rules_dir.glob("*.yaml")):
            data = _load_yaml_file(path)
            block = data.get("rules")
            if block is None and isinstance(data, dict) and "name" in data:
                block = [data]
            elif block is None:
                block = []
            for spec in _parse_rules_block(block, path):
                if spec.name in specs_by_name:
                    other = specs_by_name[spec.name][1]
                    raise ValueError(
                        f"Duplicate rule name '{spec.name}' in {path} (already defined in {other})"
                    )
                specs_by_name[spec.name] = (spec, path)

    if not specs_by_name:
        raise ValueError(
            f"No rules defined in {kompose_dir} "
            f"(expected rules.yaml and/or rules/*.yaml)"
        )

    return globals_dict, [spec for spec, _ in specs_by_name.values()]


HandlerFn = Callable[[LintContext, dict, set], list[Issue]]


def resolve_handler(spec: RuleSpec) -> HandlerFn:
    """Return the callable that implements a rule."""
    if spec.type:
        module = importlib.import_module(_BUILTIN_TYPE_PREFIX)
        fn = getattr(module, spec.type, None)
        if fn is None:
            raise ValueError(f"Rule '{spec.name}': unknown built-in type '{spec.type}'")
        return fn
    module_path = f"{_HANDLER_PACKAGE}.{spec.handler}"
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise ValueError(
            f"Rule '{spec.name}': handler '{spec.handler}' not found ({e})"
        ) from e
    fn = getattr(module, "check", None)
    if fn is None:
        raise ValueError(
            f"Rule '{spec.name}': handler module '{module_path}' must define `check(ctx, params, exclude)`"
        )
    return fn


def run_rule(spec: RuleSpec, ctx: LintContext) -> list[Issue]:
    handler = resolve_handler(spec)
    exclude = set(spec.exclude or [])
    return handler(ctx, dict(spec.params), exclude) or []


def lint_service(
    service_dir: Path,
    rules: list[RuleSpec],
    globals_dict: dict,
) -> ServiceLintResult:
    """Run all rules against one service's compose.yml."""
    result = ServiceLintResult(service_name=service_dir.name)
    compose_path = service_dir / "compose.yml"
    if not compose_path.exists():
        return result

    content = compose_path.read_text()
    try:
        parsed = yaml.safe_load(content) or {}
    except yaml.YAMLError:
        parsed = {}

    ctx = LintContext(
        service_name=service_dir.name,
        compose_path=compose_path,
        content=content,
        parsed=parsed,
        globals=dict(globals_dict),
    )

    for spec in rules:
        issues = run_rule(spec, ctx)
        result.rule_results.append(RuleResult(rule=spec, issues=issues))

    return result
