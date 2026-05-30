"""Docker Compose lifecycle commands — up, down, restart, logs.

Two execution modes, auto-selected per command invocation:

- **Root mode** — when `<host>/compose.yml` exists at the host root. All
  services are unified under a single Docker Compose project via `include:`.
  Commands target this root file; service args are passed positionally to
  docker compose. Arg expansion: if an arg matches a service dir (group),
  it is expanded to all services declared in that group's compose.yml.

- **Legacy mode** — when no root compose.yml exists. Per-service iteration
  with optional layering of `base/<service>/compose.yml` + `<host>/<service>/compose.yml`.
  Preserved for hosts that have not adopted the include model.

Status (`kompose status` + its formatters / stats sources / watch loop) lives
in `status.py`, since it doesn't mutate state and has its own concerns.
"""

import subprocess
from pathlib import Path

import yaml

from .config import WORKSPACE_DIR, get_base_dir, get_host_dir, get_services
from .utils import Colors


# ---------------------------------------------------------------------------
# Root-mode helpers
# ---------------------------------------------------------------------------


def get_root_compose(host: str | None = None) -> Path | None:
    """Return the root compose file path if it exists, else None."""
    candidate = get_host_dir(host) / "compose.yml"
    return candidate if candidate.exists() else None


def parse_compose_services(compose_path: Path) -> list[str]:
    """Return the service names declared in a compose.yml file."""
    try:
        parsed = yaml.safe_load(compose_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return []
    return list((parsed.get("services") or {}).keys())


def build_service_to_group_map(host: str | None = None) -> dict[str, str]:
    """Map docker compose service name → group dir name, by walking the root compose's includes."""
    root = get_root_compose(host)
    if not root:
        return {}

    try:
        parsed = yaml.safe_load(root.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}

    mapping: dict[str, str] = {}
    host_dir = root.parent
    for entry in parsed.get("include") or []:
        include_path = entry if isinstance(entry, str) else (entry or {}).get("path", "")
        if not include_path:
            continue
        path_obj = Path(include_path)
        if len(path_obj.parts) < 2:
            continue
        group = path_obj.parts[-2]
        full = host_dir / include_path
        if not full.exists():
            continue
        for svc in parse_compose_services(full):
            mapping[svc] = group
    return mapping


def resolve_root_targets(
    host: str | None,
    service_arg: str | None,
    container_args: list[str] | None,
) -> list[str]:
    """Resolve CLI args to a list of docker compose service names.

    Rules:
      - no service_arg                  → [] (all services)
      - service_arg + container_args    → container_args verbatim (positional)
      - service_arg matches a group dir → expand to that group's services
      - otherwise                       → [service_arg] (assume it's a service name)
    """
    if not service_arg:
        return []
    if container_args:
        return list(container_args)
    group_compose = get_host_dir(host) / service_arg / "compose.yml"
    if group_compose.exists():
        services = parse_compose_services(group_compose)
        if services:
            return services
    return [service_arg]


def run_root_compose(
    host: str | None,
    action: str,
    services: list[str],
    extra_args: list[str] | None = None,
) -> int:
    """Invoke `docker compose -f <root> <action> [extra_args] [services...]`."""
    root = get_root_compose(host)
    if root is None:
        print(f"{Colors.RED}Error: No root compose.yml at {get_host_dir(host)}{Colors.RESET}")
        return 1

    cmd = ["docker", "compose", "-f", str(root), action]
    cmd.extend(extra_args or [])
    cmd.extend(services)

    print(f"{Colors.GRAY}[{root.relative_to(WORKSPACE_DIR)}]{Colors.RESET}")
    try:
        return subprocess.run(cmd, cwd=root.parent).returncode
    except KeyboardInterrupt:
        print()
        return 130


# ---------------------------------------------------------------------------
# Legacy-mode helpers (base + host layering, per-service iteration)
# ---------------------------------------------------------------------------


def get_compose_files(service: str, host: str | None = None) -> list[Path]:
    """Get layered compose files for a service: base/<svc>/compose.yml + <host>/<svc>/compose.yml.

    Used by the legacy per-service flow when no root compose exists.
    """
    base_dir = get_base_dir()
    host_dir = get_host_dir(host)

    base_compose = base_dir / service / "compose.yml"
    host_compose = host_dir / service / "compose.yml"

    files = []
    if base_compose.exists():
        files.append(base_compose)
    if host_compose.exists():
        files.append(host_compose)

    return files


def build_compose_command(
    compose_files: list[Path],
    action: str,
    extra_args: list[str] | None = None,
    containers: list[str] | None = None,
) -> list[str]:
    """Build the docker compose command for the legacy flow."""
    cmd = ["docker", "compose"]
    for f in compose_files:
        cmd.extend(["-f", str(f)])
    cmd.append(action)
    if extra_args:
        cmd.extend(extra_args)
    if containers:
        cmd.extend(containers)
    return cmd


def run_compose(
    service: str,
    action: str,
    host: str | None = None,
    extra_args: list[str] | None = None,
    containers: list[str] | None = None,
) -> int:
    """Run docker compose for a single service in legacy mode (with layering)."""
    compose_files = get_compose_files(service, host)

    if not compose_files:
        print(f"{Colors.RED}Error: No compose.yml found for service '{service}'{Colors.RESET}")
        return 1

    cmd = build_compose_command(compose_files, action, extra_args, containers)

    files_str = " + ".join(str(f.relative_to(WORKSPACE_DIR)) for f in compose_files)
    print(f"{Colors.GRAY}[{files_str}]{Colors.RESET}")

    try:
        return subprocess.run(cmd, cwd=WORKSPACE_DIR).returncode
    except KeyboardInterrupt:
        print()
        return 130


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_up(args) -> int:
    """Start services."""
    host = getattr(args, "host", None)
    service = getattr(args, "service", None)
    containers = getattr(args, "containers", None) or None

    if get_root_compose(host):
        services = resolve_root_targets(host, service, containers)
        return run_root_compose(host, "up", services, ["-d"])

    # Legacy
    if service:
        return run_compose(service, "up", host, ["-d"], containers)
    services_dirs = get_services(host)
    if not services_dirs:
        print(f"{Colors.YELLOW}No services found{Colors.RESET}")
        return 0
    failed = 0
    for service_dir in services_dirs:
        print(f"\n{Colors.BOLD}{service_dir.name}{Colors.RESET}")
        if run_compose(service_dir.name, "up", host, ["-d"]) != 0:
            failed += 1
    if failed:
        print(f"\n{Colors.RED}{failed} service(s) failed to start{Colors.RESET}")
        return 1
    print(f"\n{Colors.GREEN}All services started{Colors.RESET}")
    return 0


def cmd_down(args) -> int:
    """Stop services."""
    host = getattr(args, "host", None)
    service = getattr(args, "service", None)
    containers = getattr(args, "containers", None) or None

    if get_root_compose(host):
        services = resolve_root_targets(host, service, containers)
        return run_root_compose(host, "down", services)

    # Legacy
    if service:
        return run_compose(service, "down", host, containers=containers)
    services_dirs = get_services(host)
    if not services_dirs:
        print(f"{Colors.YELLOW}No services found{Colors.RESET}")
        return 0
    failed = 0
    for service_dir in services_dirs:
        print(f"\n{Colors.BOLD}{service_dir.name}{Colors.RESET}")
        if run_compose(service_dir.name, "down", host) != 0:
            failed += 1
    if failed:
        print(f"\n{Colors.RED}{failed} service(s) failed to stop{Colors.RESET}")
        return 1
    print(f"\n{Colors.GREEN}All services stopped{Colors.RESET}")
    return 0


def cmd_restart(args) -> int:
    """Restart services (down + up)."""
    host = getattr(args, "host", None)
    service = getattr(args, "service", None)
    containers = getattr(args, "containers", None) or None

    if get_root_compose(host):
        services = resolve_root_targets(host, service, containers)
        label = ", ".join(services) if services else "all"
        print(f"{Colors.BOLD}Stopping {label}...{Colors.RESET}")
        result = run_root_compose(host, "down", services)
        if result != 0:
            return result
        print(f"\n{Colors.BOLD}Starting {label}...{Colors.RESET}")
        return run_root_compose(host, "up", services, ["-d"])

    # Legacy
    if service:
        print(f"{Colors.BOLD}Stopping {service}...{Colors.RESET}")
        result = run_compose(service, "down", host, containers=containers)
        if result != 0:
            return result
        print(f"\n{Colors.BOLD}Starting {service}...{Colors.RESET}")
        return run_compose(service, "up", host, ["-d"], containers)

    services_dirs = get_services(host)
    if not services_dirs:
        print(f"{Colors.YELLOW}No services found{Colors.RESET}")
        return 0
    failed = 0
    for service_dir in services_dirs:
        print(f"\n{Colors.BOLD}Restarting {service_dir.name}...{Colors.RESET}")
        if run_compose(service_dir.name, "down", host) != 0:
            failed += 1
            continue
        if run_compose(service_dir.name, "up", host, ["-d"]) != 0:
            failed += 1
    if failed:
        print(f"\n{Colors.RED}{failed} service(s) failed to restart{Colors.RESET}")
        return 1
    print(f"\n{Colors.GREEN}All services restarted{Colors.RESET}")
    return 0


def cmd_logs(args) -> int:
    """View service logs."""
    host = getattr(args, "host", None)
    service = getattr(args, "service", None)
    containers = getattr(args, "containers", None) or None
    follow = getattr(args, "follow", True)
    tail = getattr(args, "tail", "100")

    if not service:
        print(f"{Colors.RED}Error: Service name required for logs{Colors.RESET}")
        return 1

    extra_args = ["--tail", str(tail)]
    if follow:
        extra_args.append("-f")

    if get_root_compose(host):
        services = resolve_root_targets(host, service, containers)
        return run_root_compose(host, "logs", services, extra_args)

    return run_compose(service, "logs", host, extra_args, containers)

