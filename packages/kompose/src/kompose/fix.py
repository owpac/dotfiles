"""Fix command — orchestrates rule auto-fixes and delegates to env fix.

For each service, every rule that defines a `fix()` hook is invoked once.
The env-drift workflow (`cmd_env_fix`) is then chained at the end, since
its interactivity model doesn't fit the per-service hook pattern.

Flags:
  -f / --force   Skip confirmation prompts; apply defaults.
  --dry-run      Preview what would be done; do not mutate files. The env fix
                 step is skipped in dry-run mode (it's interactive by design).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ._engine import (
    FixApplied,
    LintContext,
    RuleSpec,
    load_rules,
    run_fix,
)
from .config import get_host_dir, get_services
from .env import cmd_env_fix
from .utils import Colors


def cmd_fix(args) -> int:
    service_name = getattr(args, "service", None)
    host = getattr(args, "host", None)
    force = getattr(args, "force", False)
    dry_run = getattr(args, "dry_run", False)

    host_dir = get_host_dir(host)

    try:
        globals_dict, rules = load_rules(host)
    except (FileNotFoundError, ValueError) as e:
        print(f"{Colors.RED}Error: {e}{Colors.RESET}")
        return 1

    if service_name:
        target = host_dir / service_name
        if not target.exists():
            print(f"{Colors.RED}Error: Service not found: {service_name}{Colors.RESET}")
            return 1
        services: list[Path] = [target]
    else:
        services = get_services(host)

    fixes: list[tuple[RuleSpec, FixApplied]] = []
    for service_dir in services:
        compose_path = service_dir / "compose.yml"
        if not compose_path.exists():
            continue
        ctx = _build_ctx(service_dir, compose_path, globals_dict)
        for spec in rules:
            for applied in run_fix(spec, ctx, force=force, dry_run=dry_run):
                fixes.append((spec, applied))

    _render_fixes(fixes, dry_run=dry_run)

    if dry_run:
        print(f"\n{Colors.GRAY}(dry-run: skipping interactive env fix){Colors.RESET}")
        return 0

    if fixes:
        print()  # spacer before the env section
    print(f"{Colors.BOLD}Running env fix…{Colors.RESET}")
    return cmd_env_fix(args)


def _build_ctx(service_dir: Path, compose_path: Path, globals_dict: dict) -> LintContext:
    content = compose_path.read_text()
    try:
        parsed = yaml.safe_load(content) or {}
    except yaml.YAMLError:
        parsed = {}
    return LintContext(
        service_name=service_dir.name,
        compose_path=compose_path,
        content=content,
        parsed=parsed,
        globals=dict(globals_dict),
    )


def _render_fixes(fixes: list[tuple[RuleSpec, FixApplied]], *, dry_run: bool) -> None:
    if not fixes:
        verb = "Would auto-fix" if dry_run else "Auto-fixed"
        print(f"\n{Colors.GRAY}{verb}: nothing.{Colors.RESET}")
        return

    verb = "Would auto-fix" if dry_run else "Auto-fixed"
    print(f"\n{Colors.BOLD}{verb} {len(fixes)} item(s):{Colors.RESET}")
    glyph = "→" if dry_run else "✓"
    color = Colors.GRAY if dry_run else Colors.GREEN
    for spec, applied in fixes:
        location = f" {Colors.GRAY}{applied.target}{Colors.RESET}" if applied.target else ""
        print(f"  {color}{glyph}{Colors.RESET} {Colors.CYAN}{spec.name}{Colors.RESET}:{location} {applied.message}")
