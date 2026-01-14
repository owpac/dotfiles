"""Lint command for checking compose.yml files."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import LintConfig, get_host_dir, get_services, load_config
from .utils import Colors, Table

COMPOSE_PROPERTY_ORDER = [
    "container_name", "depends_on", "env_file", "environment", "healthcheck",
    "image", "labels", "logging", "networks", "ports", "restart", "user", "volumes",
]


@dataclass
class LintIssue:
    category: str
    message: str
    fix: str = ""


@dataclass
class ServiceLint:
    name: str
    path: Path
    order_issues: list[LintIssue] = field(default_factory=list)
    router_issues: list[str] = field(default_factory=list)
    middleware_issues: list[str] = field(default_factory=list)
    config_issues: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.order_issues or self.router_issues or self.middleware_issues or self.config_issues)

    @property
    def error_count(self) -> int:
        return len(self.order_issues) + len(self.router_issues) + len(self.middleware_issues) + len(self.config_issues)


def extract_compose_service_props(content: str) -> dict[str, list[tuple[str, int]]]:
    """Extract service properties from compose.yml content."""
    services = {}
    lines = content.split("\n")
    current_service = None
    in_services_block = False
    service_indent = None
    prop_indent = None

    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if stripped.startswith("services:"):
            in_services_block = True
            continue
        if not in_services_block:
            continue
        if indent == 0 and stripped and not stripped.startswith("#"):
            in_services_block = False
            continue
        if not stripped or stripped.startswith("#"):
            continue
        if service_indent is None and indent > 0 and stripped.endswith(":") and not stripped.startswith("-"):
            service_indent = indent
        if indent == service_indent and stripped.endswith(":") and not stripped.startswith("-"):
            service_name = stripped.rstrip(":").strip()
            current_service = service_name
            services[current_service] = []
            prop_indent = None
            continue
        if current_service and indent > service_indent:
            if prop_indent is None:
                prop_indent = indent
            if indent == prop_indent and ":" in stripped and not stripped.startswith("-"):
                prop_name = stripped.split(":")[0].strip()
                services[current_service].append((prop_name, i))

    return services


def find_order_fixes(props: list[tuple[str, int]]) -> list[LintIssue]:
    """Find property order issues."""
    issues = []
    prop_names = [p[0] for p in props]
    known_props = [(name, line) for name, line in props if name in COMPOSE_PROPERTY_ORDER]

    if not known_props:
        return issues

    expected_order = [p for p in COMPOSE_PROPERTY_ORDER if p in prop_names]
    actual_order = [p[0] for p in known_props]

    if actual_order == expected_order:
        return issues

    out_of_order = []
    for i, (prop, line) in enumerate(known_props):
        expected_idx = expected_order.index(prop)
        for j in range(i):
            other_prop = known_props[j][0]
            other_expected_idx = expected_order.index(other_prop)
            if other_expected_idx > expected_idx:
                out_of_order.append((prop, line, other_prop))
                break

    if out_of_order:
        moves = {}
        for prop, line, before in out_of_order:
            if prop not in moves:
                moves[prop] = {"line": line, "before": before}

        for prop, info in moves.items():
            line_num = info["line"]
            before_prop = info["before"]
            issues.append(LintIssue(
                category="order",
                message=f":{line_num}",
                fix=f"move `{prop}` before `{before_prop}`"
            ))

    return issues


def find_router_issues(content: str, exclude: set[str] | None = None) -> list[str]:
    """Check router naming conventions."""
    exclude = exclude or set()
    has_public = "owpac.com" in content

    router_pattern = r"traefik\.http\.routers\.([a-z0-9-]+)\."
    routers = set(re.findall(router_pattern, content))
    bad_routers = []

    for router in sorted(routers):
        if router == "wildcard-certs" or router in exclude:
            continue

        has_suffix = router.endswith("-private") or router.endswith("-public")

        if has_public:
            if not has_suffix:
                bad_routers.append(f"{router} (missing -private/-public)")
        else:
            if router.endswith("-public"):
                bad_routers.append(f"{router} (use -private for owpac.net)")

    return bad_routers


def find_middleware_issues(content: str, exclude: set[str] | None = None) -> list[str]:
    """Check middleware configuration."""
    exclude = exclude or set()
    issues = []

    router_pattern = r"traefik\.http\.routers\.([a-z0-9-]+)\.rule[^:]*:[^`]*`([^`]+)`"
    middleware_pattern = r"traefik\.http\.routers\.([a-z0-9-]+)\.middlewares[^:]*:[^\n]*"

    rules = dict(re.findall(router_pattern, content))

    for match in re.finditer(middleware_pattern, content):
        router = match.group(1)
        middleware_line = match.group(0)

        if router == "wildcard-certs" or router in exclude:
            continue

        rule = rules.get(router, "")
        is_public = "owpac.com" in rule
        is_private = "owpac.net" in rule

        has_wan = "wan@file" in middleware_line
        has_lan = "lan@file" in middleware_line

        if is_public and not has_wan:
            issues.append(f"{router} (public needs wan@file)")
        elif is_private and not has_lan:
            issues.append(f"{router} (private needs lan@file)")

    return issues


def find_config_issues(
    content: str,
    service_name: str,
    exclude_logging: set[str] | None = None,
    exclude_network: set[str] | None = None,
) -> list[str]:
    """Check configuration issues."""
    exclude_logging = exclude_logging or set()
    exclude_network = exclude_network or set()
    issues = []

    if service_name not in exclude_logging:
        if "logging:" not in content:
            issues.append("missing logging")
        elif "driver: local" not in content:
            issues.append("logging: use driver: local")

    if service_name not in exclude_network:
        if "reverse-proxy" not in content and "network_mode" not in content:
            issues.append("missing network: reverse-proxy")

    return issues


def lint_service(service_dir: Path, config: LintConfig) -> ServiceLint:
    """Lint a single service."""
    result = ServiceLint(name=service_dir.name, path=service_dir)
    compose_file = service_dir / "compose.yml"

    if not compose_file.exists():
        return result

    content = compose_file.read_text()
    service_props = extract_compose_service_props(content)

    for container_name, props in service_props.items():
        order_issues = find_order_fixes(props)
        for issue in order_issues:
            issue.message = f"{container_name}{issue.message}"
            result.order_issues.append(issue)

    result.router_issues = find_router_issues(content, config.exclude_routers)
    result.middleware_issues = find_middleware_issues(content, config.exclude_middlewares)
    result.config_issues = find_config_issues(
        content,
        service_dir.name,
        config.exclude_logging,
        config.exclude_network,
    )
    return result


def cmd_lint(args) -> int:
    """Execute the lint command."""
    service_name = args.service
    host = getattr(args, "host", None)
    config = load_config(host)
    host_dir = get_host_dir(host)

    if service_name:
        services = [host_dir / service_name]
        if not services[0].exists():
            print(f"{Colors.RED}Error: Service not found: {service_name}{Colors.RESET}")
            return 1
    else:
        services = get_services(host)

    results: list[ServiceLint] = []
    for service_dir in services:
        if (service_dir / "compose.yml").exists():
            results.append(lint_service(service_dir, config))

    table = Table(["Service", "Order", "Routers", "Middlewares", "Config"])
    failed_services: list[ServiceLint] = []

    for r in results:
        order_str = f"{Colors.RED}{len(r.order_issues)}{Colors.RESET}" if r.order_issues else f"{Colors.GRAY}-{Colors.RESET}"
        router_str = f"{Colors.RED}{len(r.router_issues)}{Colors.RESET}" if r.router_issues else f"{Colors.GRAY}-{Colors.RESET}"
        middleware_str = f"{Colors.RED}{len(r.middleware_issues)}{Colors.RESET}" if r.middleware_issues else f"{Colors.GRAY}-{Colors.RESET}"
        config_str = f"{Colors.RED}{len(r.config_issues)}{Colors.RESET}" if r.config_issues else f"{Colors.GRAY}-{Colors.RESET}"

        if r.has_errors:
            table.add_row([f"{Colors.RED}{r.name}{Colors.RESET}", order_str, router_str, middleware_str, config_str])
            failed_services.append(r)
        else:
            table.add_row([f"{Colors.GREEN}{r.name}{Colors.RESET}", order_str, router_str, middleware_str, config_str])

    print()
    print(table.render())

    if failed_services:
        order_services = [s for s in failed_services if s.order_issues]
        if order_services:
            print(f"\n{Colors.BOLD}Property Order{Colors.RESET}")
            for svc in order_services:
                print(f"  {Colors.CYAN}{svc.name}/compose.yml{Colors.RESET}")
                for issue in svc.order_issues:
                    print(f"    {Colors.GRAY}{issue.message}{Colors.RESET}  {issue.fix}")

        router_services = [s for s in failed_services if s.router_issues]
        if router_services:
            print(f"\n{Colors.BOLD}Router Naming{Colors.RESET}")
            for svc in router_services:
                print(f"  {Colors.CYAN}{svc.name}{Colors.RESET}")
                for issue in svc.router_issues[:5]:
                    print(f"    {issue}")
                if len(svc.router_issues) > 5:
                    print(f"    {Colors.GRAY}+{len(svc.router_issues) - 5} more{Colors.RESET}")

        middleware_services = [s for s in failed_services if s.middleware_issues]
        if middleware_services:
            print(f"\n{Colors.BOLD}Middlewares{Colors.RESET}")
            for svc in middleware_services:
                print(f"  {Colors.CYAN}{svc.name}{Colors.RESET}")
                for issue in svc.middleware_issues[:5]:
                    print(f"    {issue}")
                if len(svc.middleware_issues) > 5:
                    print(f"    {Colors.GRAY}+{len(svc.middleware_issues) - 5} more{Colors.RESET}")

        config_services = [s for s in failed_services if s.config_issues]
        if config_services:
            print(f"\n{Colors.BOLD}Configuration{Colors.RESET}")
            for svc in config_services:
                issues = ", ".join(svc.config_issues)
                print(f"  {Colors.CYAN}{svc.name}{Colors.RESET}  {issues}")

    total_errors = sum(s.error_count for s in failed_services)
    print()
    if total_errors > 0:
        print(f"{Colors.RED}{total_errors} issue(s) in {len(failed_services)} service(s){Colors.RESET}")
        return 1
    else:
        print(f"{Colors.GREEN}All {len(results)} services passed{Colors.RESET}")
        return 0
