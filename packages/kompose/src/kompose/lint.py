"""Lint command — orchestrates rule loading, execution, and reporting."""

from __future__ import annotations

from pathlib import Path

from ._engine import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    Issue,
    RuleSpec,
    ServiceLintResult,
    lint_service,
    load_rules,
    resolve_fix,
    run_notices,
)
from .config import get_host_dir, get_services
from .utils import Colors, Table


def _categories(rules) -> list[str]:
    """Categories in order of first appearance."""
    seen: dict[str, None] = {}
    for r in rules:
        seen.setdefault(r.category, None)
    return list(seen.keys())


def _render_count(error_count: int, warning_count: int) -> str:
    if error_count == 0 and warning_count == 0:
        return f"{Colors.GRAY}-{Colors.RESET}"
    parts = []
    if error_count:
        parts.append(f"{Colors.RED}{error_count}{Colors.RESET}")
    if warning_count:
        parts.append(f"{Colors.YELLOW}{warning_count}{Colors.RESET}")
    return "/".join(parts)


def _service_color(result: ServiceLintResult) -> str:
    if result.error_count:
        return Colors.RED
    if result.warning_count:
        return Colors.YELLOW
    return Colors.GREEN


def _render_notices(notices_by_rule: list[tuple[RuleSpec, list[Issue]]]) -> str:
    """Render host-wide notices (one entry per rule that produced them)."""
    blocks: list[str] = []
    for spec, issues in notices_by_rule:
        if not issues:
            continue
        sev_color = Colors.RED if spec.severity == SEVERITY_ERROR else Colors.YELLOW
        header = f"\n{Colors.BOLD}Notices — {Colors.CYAN}{spec.name}{Colors.RESET}"
        lines = [header]
        for issue in issues:
            location = f" {Colors.GRAY}{issue.location}{Colors.RESET}" if issue.location else ""
            lines.append(f"  {sev_color}●{Colors.RESET}{location} {issue.message}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _render_details(results: list[ServiceLintResult]) -> str:
    """Print issues grouped by service, with rule name + message per line."""
    lines: list[str] = []
    for r in results:
        if r.error_count == 0 and r.warning_count == 0:
            continue
        lines.append(f"\n{Colors.CYAN}{r.service_name}{Colors.RESET}")
        for rr in r.rule_results:
            if not rr.issues:
                continue
            sev_color = Colors.RED if rr.rule.severity == SEVERITY_ERROR else Colors.YELLOW
            for issue in rr.issues:
                tag = f"{sev_color}{rr.rule.name}{Colors.RESET}"
                msg = issue.message
                location = f" {Colors.GRAY}{issue.location}{Colors.RESET}" if issue.location else ""
                fix = f"  {Colors.GRAY}→ {issue.fix}{Colors.RESET}" if issue.fix else ""
                lines.append(f"  {tag}:{location} {msg}{fix}")
    return "\n".join(lines)


def cmd_check(args) -> int:
    service_name = getattr(args, "service", None)
    host = getattr(args, "host", None)

    host_dir = get_host_dir(host)

    try:
        globals_dict, rules = load_rules(host)
    except (FileNotFoundError, ValueError) as e:
        print(f"{Colors.RED}Error: {e}{Colors.RESET}")
        print(f"{Colors.GRAY}Hint: run `kompose doctor --rules` for a structured report.{Colors.RESET}")
        return 1

    if service_name:
        target = host_dir / service_name
        if not target.exists():
            print(f"{Colors.RED}Error: Service not found: {service_name}{Colors.RESET}")
            return 1
        services: list[Path] = [target]
    else:
        services = get_services(host)

    results: list[ServiceLintResult] = []
    for service_dir in services:
        if (service_dir / "compose.yml").exists():
            results.append(lint_service(service_dir, rules, globals_dict))

    categories = _categories(rules)
    table = Table(["Service", *[c.capitalize() for c in categories]])
    for r in results:
        row = [f"{_service_color(r)}{r.service_name}{Colors.RESET}"]
        for cat in categories:
            cat_issues = r.issues_in_category(cat)
            err = sum(1 for rr in r.rule_results if rr.rule.category == cat and rr.rule.severity == SEVERITY_ERROR for _ in rr.issues)
            warn = sum(1 for rr in r.rule_results if rr.rule.category == cat and rr.rule.severity == SEVERITY_WARNING for _ in rr.issues)
            if not cat_issues:
                row.append(f"{Colors.GRAY}-{Colors.RESET}")
            else:
                row.append(_render_count(err, warn))
        table.add_row(row)

    print()
    print(table.render())

    detail_block = _render_details(results)
    if detail_block:
        print(detail_block)

    # Collect host-wide notices from every rule that defines a notices() hook.
    # Only invoked once per host (not per-service).
    notice_services = get_services(host) if not service_name else services
    notices_by_rule: list[tuple[RuleSpec, list[Issue]]] = []
    notice_errors = 0
    notice_warnings = 0
    for spec in rules:
        issues = run_notices(spec, host_dir, notice_services)
        if issues:
            notices_by_rule.append((spec, issues))
            if spec.severity == SEVERITY_ERROR:
                notice_errors += len(issues)
            else:
                notice_warnings += len(issues)

    notices_block = _render_notices(notices_by_rule)
    if notices_block:
        print(notices_block)

    total_errors = sum(r.error_count for r in results) + notice_errors
    total_warnings = sum(r.warning_count for r in results) + notice_warnings
    failed_services = sum(1 for r in results if r.has_errors)

    # Count issues whose rule advertises a fix() — surfaced as a footer hint.
    fixable_rules = {spec.name for spec in rules if resolve_fix(spec) is not None}
    fixable_count = 0
    for r in results:
        for rr in r.rule_results:
            if rr.rule.name in fixable_rules:
                fixable_count += len(rr.issues)
    for spec, issues in notices_by_rule:
        if spec.name in fixable_rules:
            fixable_count += len(issues)

    print()
    if total_errors == 0 and total_warnings == 0:
        print(f"{Colors.GREEN}All {len(results)} services passed{Colors.RESET}")
        return 0
    if total_errors == 0:
        print(f"{Colors.YELLOW}{total_warnings} warning(s){Colors.RESET}")
    else:
        parts = [f"{Colors.RED}{total_errors} error(s){Colors.RESET}"]
        if failed_services:
            parts.append(f"in {failed_services} service(s)")
        if notice_errors:
            parts.append(f"({notice_errors} host-wide)")
        summary = " ".join(parts)
        if total_warnings:
            summary += f" {Colors.YELLOW}+ {total_warnings} warning(s){Colors.RESET}"
        print(summary)

    if fixable_count:
        print(f"{Colors.GRAY}→ {fixable_count} auto-fixable. Run `kompose fix` to apply.{Colors.RESET}")

    return 0 if total_errors == 0 else 1
