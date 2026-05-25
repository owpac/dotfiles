"""Lint command — orchestrates rule loading, execution, and reporting."""

from __future__ import annotations

from pathlib import Path

from ._engine import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    ServiceLintResult,
    lint_service,
    load_rules,
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
        parts.append(f"{Colors.YELLOW}{warning_count}!{Colors.RESET}")
    return "/".join(parts)


def _service_color(result: ServiceLintResult) -> str:
    if result.error_count:
        return Colors.RED
    if result.warning_count:
        return Colors.YELLOW
    return Colors.GREEN


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


def cmd_lint(args) -> int:
    service_name = getattr(args, "service", None)
    host = getattr(args, "host", None)

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

    total_errors = sum(r.error_count for r in results)
    total_warnings = sum(r.warning_count for r in results)
    failed = sum(1 for r in results if r.has_errors)

    print()
    if total_errors == 0 and total_warnings == 0:
        print(f"{Colors.GREEN}All {len(results)} services passed{Colors.RESET}")
        return 0
    if total_errors == 0:
        print(f"{Colors.YELLOW}{total_warnings} warning(s){Colors.RESET}")
        return 0
    summary = f"{Colors.RED}{total_errors} error(s) in {failed} service(s){Colors.RESET}"
    if total_warnings:
        summary += f" {Colors.YELLOW}+ {total_warnings} warning(s){Colors.RESET}"
    print(summary)
    return 1
