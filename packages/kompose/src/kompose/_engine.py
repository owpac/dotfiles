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


def load_kompose_config(host: str | None = None) -> dict:
    """Load the optional `kompose:` section from .kompose/ — CLI-level settings.

    Distinct from `globals:` (which feeds lint handlers via ctx.globals). The
    `kompose:` block holds settings consumed by the CLI itself (e.g.
    `kompose.watchtower.url`). Returns `{}` if absent.
    """
    kompose_dir = get_kompose_dir(host)
    if not kompose_dir.exists():
        return {}

    merged: dict = {}
    for candidate in (kompose_dir / "rules.yaml", kompose_dir / "globals.yaml"):
        if candidate.exists():
            data = _load_yaml_file(candidate)
            section = data.get("kompose")
            if isinstance(section, dict):
                merged.update(section)
    return merged


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
NoticesFn = Callable[[Path, list, dict, set], list[Issue]]
FixFn = Callable[..., list["FixApplied"]]


@dataclass
class FixApplied:
    """Description of an auto-fix that was applied (or would be in dry-run)."""
    target: str           # human path, e.g. 'paperless/compose.yml' or 'paperless/.env'
    message: str          # short description, e.g. 'reordered 4 properties'
    before: str = ""      # optional snippet, used by --dry-run renderers
    after: str = ""       # optional snippet


def _handler_module(spec: RuleSpec):
    """Import and return the module that backs the rule's handler/type."""
    if spec.type:
        return importlib.import_module(_BUILTIN_TYPE_PREFIX)
    module_path = f"{_HANDLER_PACKAGE}.{spec.handler}"
    try:
        return importlib.import_module(module_path)
    except ImportError as e:
        raise ValueError(
            f"Rule '{spec.name}': handler '{spec.handler}' not found ({e})"
        ) from e


def resolve_handler(spec: RuleSpec) -> HandlerFn:
    """Return the per-service callable that implements a rule."""
    module = _handler_module(spec)
    if spec.type:
        fn = getattr(module, spec.type, None)
        if fn is None:
            raise ValueError(f"Rule '{spec.name}': unknown built-in type '{spec.type}'")
        return fn
    fn = getattr(module, "check", None)
    if fn is None:
        module_path = f"{_HANDLER_PACKAGE}.{spec.handler}"
        raise ValueError(
            f"Rule '{spec.name}': handler module '{module_path}' must define `check(ctx, params, exclude)`"
        )
    return fn


def resolve_notices(spec: RuleSpec) -> NoticesFn | None:
    """Return the rule's optional `notices()` callable, or None.

    For Python handlers, looks for a `notices` function in the handler module.
    For built-in types, looks for `<type>_notices` in the built-in module.
    """
    module = _handler_module(spec)
    if spec.type:
        return getattr(module, f"{spec.type}_notices", None)
    return getattr(module, "notices", None)


def run_rule(spec: RuleSpec, ctx: LintContext) -> list[Issue]:
    handler = resolve_handler(spec)
    exclude = set(spec.exclude or [])
    return handler(ctx, dict(spec.params), exclude) or []


def run_notices(
    spec: RuleSpec,
    host_dir: Path,
    services: list[Path],
) -> list[Issue]:
    """Invoke a rule's `notices()` hook if defined, else return []."""
    fn = resolve_notices(spec)
    if fn is None:
        return []
    exclude = set(spec.exclude or [])
    return fn(host_dir, services, dict(spec.params), exclude) or []


def resolve_fix(spec: RuleSpec) -> FixFn | None:
    """Return the rule's optional `fix()` callable, or None.

    Convention identical to notices: `fix` attr on handler modules, or
    `<type>_fix` for built-in types.
    """
    module = _handler_module(spec)
    if spec.type:
        return getattr(module, f"{spec.type}_fix", None)
    return getattr(module, "fix", None)


def run_fix(
    spec: RuleSpec,
    ctx: LintContext,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> list[FixApplied]:
    """Invoke a rule's `fix()` hook if defined, else return [].

    The rule itself is responsible for honouring `dry_run` (not mutating
    the filesystem) and `force` (skipping confirmation prompts).
    """
    fn = resolve_fix(spec)
    if fn is None:
        return []
    exclude = set(spec.exclude or [])
    return fn(ctx, dict(spec.params), exclude, force=force, dry_run=dry_run) or []


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
