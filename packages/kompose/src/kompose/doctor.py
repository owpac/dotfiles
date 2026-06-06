"""Doctor — validate kompose's own config in `<host>/.kompose/`.

Surfaces issues that would otherwise only appear when a command tries to use
the misconfigured value at runtime (handler import error, action container
that doesn't exist, etc.).

Distinct from `kompose check` which lints user services' `compose.yml` files
against the rules. Doctor lints the rules themselves and the commands map.
"""

from __future__ import annotations

import argparse
import importlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from ._engine import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    get_kompose_dir,
    load_rules,
)
from .commands import load_commands
from .config import get_host_dir
from .utils import Colors


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


@dataclass
class DoctorFinding:
    severity: str       # SEVERITY_ERROR or SEVERITY_WARNING
    source: str         # logical file name: "rules.yaml", "commands.yaml", ".kompose/"
    message: str
    location: str = ""  # optional context (e.g. "rule 'foo'", "crowdsec:hub-upgrade")


# Built-in argparse types in kompose.rules._builtin that user rules can reference
# via `type:`. Discovered at runtime to avoid drift with the module.
def _builtin_types() -> set[str]:
    from .rules import _builtin
    return {
        name for name in dir(_builtin)
        if not name.startswith("_")
        and callable(getattr(_builtin, name))
        # Skip the `_notices` / `_fix` companions; we only check primary handlers.
        and not name.endswith("_notices")
        and not name.endswith("_fix")
    }


def _kompose_subcommand_names() -> set[str]:
    """Collect every top-level kompose subcommand + alias by building the
    parser. Used to flag action names that would shadow a built-in command.
    """
    # Local import to avoid a circular dep at module load time.
    from .__main__ import _build_parser
    parser = _build_parser()
    names: set[str] = set()
    for action in parser._subparsers._actions:  # type: ignore[union-attr]
        if isinstance(action, argparse._SubParsersAction):
            names.update(action.choices.keys())
    return names


# ---------------------------------------------------------------------------
# rules.yaml checks
# ---------------------------------------------------------------------------


def check_rules_yaml(host: str | None = None) -> list[DoctorFinding]:
    """Verify rules referenced in `<host>/.kompose/rules.yaml` actually resolve."""
    findings: list[DoctorFinding] = []
    kompose_dir = get_kompose_dir(host)
    # Both "missing dir" and "dir present but no rules*.yaml" mean there's
    # nothing to validate here. check_general surfaces the missing-dir case.
    if not kompose_dir.exists():
        return findings
    if not (kompose_dir / "rules.yaml").exists() and not (kompose_dir / "rules").is_dir():
        return findings
    try:
        _, rules = load_rules(host)
    except (FileNotFoundError, ValueError, LookupError) as e:
        # LookupError covers `KeyError` from `_parse_rules_block` when a
        # rule entry is missing a required key (e.g. `name:`).
        findings.append(DoctorFinding(SEVERITY_ERROR, "rules.yaml", str(e) or type(e).__name__))
        return findings

    builtin_types = _builtin_types()

    for spec in rules:
        if spec.handler:
            module_path = f"kompose.rules.{spec.handler}"
            try:
                importlib.import_module(module_path)
            except ImportError as e:
                findings.append(DoctorFinding(
                    SEVERITY_ERROR, "rules.yaml",
                    f"handler '{spec.handler}' is not importable: {e}",
                    location=f"rule '{spec.name}'",
                ))
        elif spec.type and spec.type not in builtin_types:
            findings.append(DoctorFinding(
                SEVERITY_ERROR, "rules.yaml",
                f"type '{spec.type}' is not a known built-in (expected one of: {', '.join(sorted(builtin_types))})",
                location=f"rule '{spec.name}'",
            ))

        # `exclude:` semantics are handler/type-specific (service names,
        # router names, container names, …) — doctor can't validate them
        # without per-handler knowledge. Skipped on purpose.

    return findings


# ---------------------------------------------------------------------------
# commands.yaml checks
# ---------------------------------------------------------------------------


def _compose_containers(compose_path: Path) -> set[str]:
    """Return the set of container/service names declared in a compose.yml."""
    try:
        parsed = yaml.safe_load(compose_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return set()
    services = parsed.get("services") or {}
    return set(services.keys()) if isinstance(services, dict) else set()


def check_commands_yaml(host: str | None = None) -> list[DoctorFinding]:
    """Verify each action's target container/service is present and the action
    name doesn't shadow a built-in kompose subcommand.
    """
    findings: list[DoctorFinding] = []
    try:
        actions = load_commands(host)
    except ValueError as e:
        findings.append(DoctorFinding(SEVERITY_ERROR, "commands.yaml", str(e)))
        return findings

    if not actions:
        return findings

    host_dir = get_host_dir(host)
    reserved = _kompose_subcommand_names()

    for action in actions:
        service_dir = host_dir / action.service
        compose_path = service_dir / "compose.yml"

        if not compose_path.exists():
            findings.append(DoctorFinding(
                SEVERITY_ERROR, "commands.yaml",
                f"service '{action.service}' has no compose.yml at {compose_path.relative_to(host_dir.parent)}",
                location=action.qualified_name,
            ))
        else:
            containers = _compose_containers(compose_path)
            if action.container not in containers:
                findings.append(DoctorFinding(
                    SEVERITY_ERROR, "commands.yaml",
                    f"container '{action.container}' not declared in {compose_path.relative_to(host_dir.parent)} "
                    f"(found: {', '.join(sorted(containers)) or '(none)'})",
                    location=action.qualified_name,
                ))

        if action.name in reserved:
            findings.append(DoctorFinding(
                SEVERITY_WARNING, "commands.yaml",
                f"action name '{action.name}' shadows a kompose built-in subcommand — "
                f"the bare `kompose run {action.name}` still works, but it may surprise readers",
                location=action.qualified_name,
            ))

    return findings


# ---------------------------------------------------------------------------
# General checks (.kompose/ presence, etc.)
# ---------------------------------------------------------------------------


def check_general(host: str | None = None) -> list[DoctorFinding]:
    """Sanity checks that aren't tied to a single config file."""
    findings: list[DoctorFinding] = []
    kompose_dir = get_kompose_dir(host)
    if not kompose_dir.exists():
        findings.append(DoctorFinding(
            SEVERITY_WARNING, ".kompose/",
            f"no .kompose/ directory at {kompose_dir} — without it, `kompose check` and "
            f"`kompose run` have nothing to read",
        ))
    return findings


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


_ICON_ERROR = "✗"
_ICON_WARNING = "⚠"


def _severity_color(severity: str) -> str:
    return Colors.RED if severity == SEVERITY_ERROR else Colors.YELLOW


def _severity_icon(severity: str) -> str:
    return _ICON_ERROR if severity == SEVERITY_ERROR else _ICON_WARNING


def _render(findings: list[DoctorFinding]) -> str:
    """Group findings by source file and render with severity icons."""
    if not findings:
        return f"{Colors.GREEN}✓ kompose config looks good{Colors.RESET}"

    by_source: dict[str, list[DoctorFinding]] = {}
    for f in findings:
        by_source.setdefault(f.source, []).append(f)

    lines: list[str] = []
    for source in sorted(by_source):
        lines.append(f"\n{Colors.CYAN}{source}{Colors.RESET}")
        for f in by_source[source]:
            icon = f"{_severity_color(f.severity)}{_severity_icon(f.severity)}{Colors.RESET}"
            location = f"  {Colors.GRAY}{f.location}{Colors.RESET}" if f.location else ""
            lines.append(f"  {icon}{location}  {f.message}")

    errors = sum(1 for f in findings if f.severity == SEVERITY_ERROR)
    warnings = sum(1 for f in findings if f.severity == SEVERITY_WARNING)
    summary_parts: list[str] = []
    if errors:
        summary_parts.append(f"{Colors.RED}{errors} error{'s' if errors > 1 else ''}{Colors.RESET}")
    if warnings:
        summary_parts.append(f"{Colors.YELLOW}{warnings} warning{'s' if warnings > 1 else ''}{Colors.RESET}")
    lines.append(f"\n{' · '.join(summary_parts)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def cmd_doctor(args) -> int:
    """`kompose doctor [--rules] [--commands]`.

    No flags → check everything. Flags scope to specific concerns.
    """
    host = getattr(args, "host", None)
    only_rules = getattr(args, "rules", False)
    only_commands = getattr(args, "commands", False)
    scoped = only_rules or only_commands

    findings: list[DoctorFinding] = []
    if not scoped:
        findings.extend(check_general(host))
    if not scoped or only_rules:
        findings.extend(check_rules_yaml(host))
    if not scoped or only_commands:
        findings.extend(check_commands_yaml(host))

    print(_render(findings))
    return 1 if any(f.severity == SEVERITY_ERROR for f in findings) else 0
