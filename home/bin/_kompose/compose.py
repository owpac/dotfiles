"""Docker Compose commands (up, down, restart, logs, ps)."""

import subprocess
import sys
from pathlib import Path

from .config import WORKSPACE_DIR, get_base_dir, get_host_dir, get_services
from .utils import Colors, Table


def get_compose_files(service: str, host: str | None = None) -> list[Path]:
    """Get compose files for a service, handling base + host layering."""
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


def build_compose_command(compose_files: list[Path], action: str, extra_args: list[str] | None = None) -> list[str]:
    """Build the docker compose command."""
    cmd = ["docker", "compose"]
    for f in compose_files:
        cmd.extend(["-f", str(f)])
    cmd.append(action)
    if extra_args:
        cmd.extend(extra_args)
    return cmd


def run_compose(service: str, action: str, host: str | None = None, extra_args: list[str] | None = None) -> int:
    """Run docker compose command for a service."""
    compose_files = get_compose_files(service, host)

    if not compose_files:
        print(f"{Colors.RED}Error: No compose.yml found for service '{service}'{Colors.RESET}")
        return 1

    cmd = build_compose_command(compose_files, action, extra_args)

    # Show which files we're using
    files_str = " + ".join(str(f.relative_to(WORKSPACE_DIR)) for f in compose_files)
    print(f"{Colors.GRAY}[{files_str}]{Colors.RESET}")

    try:
        result = subprocess.run(cmd, cwd=WORKSPACE_DIR)
        return result.returncode
    except KeyboardInterrupt:
        print()
        return 130


def cmd_up(args) -> int:
    """Start services."""
    host = getattr(args, "host", None)
    service = getattr(args, "service", None)

    if service:
        return run_compose(service, "up", host, ["-d"])
    else:
        # Start all services
        services = get_services(host)
        if not services:
            print(f"{Colors.YELLOW}No services found{Colors.RESET}")
            return 0

        failed = 0
        for service_dir in services:
            print(f"\n{Colors.BOLD}{service_dir.name}{Colors.RESET}")
            result = run_compose(service_dir.name, "up", host, ["-d"])
            if result != 0:
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

    if service:
        return run_compose(service, "down", host)
    else:
        # Stop all services
        services = get_services(host)
        if not services:
            print(f"{Colors.YELLOW}No services found{Colors.RESET}")
            return 0

        failed = 0
        for service_dir in services:
            print(f"\n{Colors.BOLD}{service_dir.name}{Colors.RESET}")
            result = run_compose(service_dir.name, "down", host)
            if result != 0:
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

    if service:
        print(f"{Colors.BOLD}Stopping {service}...{Colors.RESET}")
        result = run_compose(service, "down", host)
        if result != 0:
            return result
        print(f"\n{Colors.BOLD}Starting {service}...{Colors.RESET}")
        return run_compose(service, "up", host, ["-d"])
    else:
        # Restart all services
        services = get_services(host)
        if not services:
            print(f"{Colors.YELLOW}No services found{Colors.RESET}")
            return 0

        failed = 0
        for service_dir in services:
            print(f"\n{Colors.BOLD}Restarting {service_dir.name}...{Colors.RESET}")
            result = run_compose(service_dir.name, "down", host)
            if result != 0:
                failed += 1
                continue
            result = run_compose(service_dir.name, "up", host, ["-d"])
            if result != 0:
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
    follow = getattr(args, "follow", True)
    tail = getattr(args, "tail", "100")

    if not service:
        print(f"{Colors.RED}Error: Service name required for logs{Colors.RESET}")
        return 1

    extra_args = ["--tail", str(tail)]
    if follow:
        extra_args.append("-f")

    return run_compose(service, "logs", host, extra_args)


def get_network_containers(network: str = "reverse-proxy") -> dict[str, dict]:
    """Get containers and their IPs from a docker network."""
    import json

    cmd = ["docker", "network", "inspect", network, "--format", "{{ json .Containers }}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return {}

        containers_data = json.loads(result.stdout.strip())
        containers = {}
        for container_id, info in containers_data.items():
            name = info.get("Name", "")
            ipv4 = info.get("IPv4Address", "").split("/")[0]
            ipv6 = info.get("IPv6Address", "").split("/")[0]
            containers[name] = {
                "ipv4": ipv4,
                "ipv6": ipv6,
            }
        return containers
    except Exception:
        return {}


def get_all_containers_info() -> list[dict]:
    """Get info about all running containers using docker ps."""
    import json

    cmd = ["docker", "ps", "--format", "json"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return []

        containers = []
        for line in result.stdout.strip().split("\n"):
            if line:
                try:
                    containers.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return containers
    except Exception:
        return []


def parse_ip_for_sort(ip: str) -> tuple:
    """Parse IP address for sorting."""
    if not ip:
        return (999, 999, 999, 999)
    try:
        parts = ip.split(".")
        return tuple(int(p) for p in parts)
    except (ValueError, AttributeError):
        return (999, 999, 999, 999)


def cmd_status(args) -> int:
    """Show status of all services with IPs."""
    host = getattr(args, "host", None)
    services = get_services(host)

    if not services:
        print(f"{Colors.YELLOW}No services found{Colors.RESET}")
        return 0

    # Get network info (IPs)
    network_containers = get_network_containers("reverse-proxy")

    # Match containers to services, grouped by service_dir
    service_groups: dict[str, list[dict]] = {}
    for service_dir in services:
        compose_files = get_compose_files(service_dir.name, host)
        if not compose_files:
            continue

        cmd = build_compose_command(compose_files, "ps", ["--format", "json", "-a"])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=WORKSPACE_DIR)
            if result.returncode == 0 and result.stdout.strip():
                import json
                for line in result.stdout.strip().split("\n"):
                    if line:
                        try:
                            container = json.loads(line)
                            container["_service_dir"] = service_dir.name
                            # Get IP for this container
                            name = container.get("Name", "")
                            container["_ip"] = network_containers.get(name, {}).get("ipv4", "")
                            if service_dir.name not in service_groups:
                                service_groups[service_dir.name] = []
                            service_groups[service_dir.name].append(container)
                        except json.JSONDecodeError:
                            pass
        except Exception:
            pass

    if not service_groups:
        print(f"{Colors.YELLOW}No containers found{Colors.RESET}")
        return 0

    # For each service group, identify main container (has IP) and dependencies
    def get_main_ip(containers: list[dict]) -> str:
        """Get the IP of the main container in a group."""
        for c in containers:
            if c.get("_ip"):
                return c["_ip"]
        return ""

    # Sort service groups by main container IP
    sorted_services = sorted(
        service_groups.items(),
        key=lambda x: parse_ip_for_sort(get_main_ip(x[1]))
    )

    # Build table
    table = Table(["Service", "Container", "Status", "IP", "Ports"])
    total_containers = 0
    running_containers = 0

    # Calculate max service name length for tree lines
    max_svc_len = max(len(svc) for svc, _ in sorted_services) if sorted_services else 0

    for service_name, containers in sorted_services:
        # Sort containers: those with IP first (by IP), then those without (alphabetically)
        containers.sort(key=lambda c: (
            not c.get("_ip"),  # IP first
            parse_ip_for_sort(c.get("_ip", "")),  # Then by IP order
            c.get("Name", "")  # Then alphabetically
        ))

        # Check if group has any container with IP
        has_main_with_ip = any(c.get("_ip") for c in containers)

        first_in_group = True
        for c in containers:
            total_containers += 1
            container_name = c.get("Name", "")
            state = c.get("State", "")
            status = c.get("Status", "")
            ip = c.get("_ip", "")

            if state == "running":
                running_containers += 1

            # A container is a dependency only if it has no IP AND group has containers with IP
            is_dependency = not ip and has_main_with_ip

            # Format service column
            if first_in_group:
                svc_str = service_name
                first_in_group = False
            elif is_dependency:
                # Extend └─ to fill column (max service name length)
                svc_str = f"{Colors.GRAY}└{'─' * (max_svc_len - 1)}{Colors.RESET}"
            else:
                svc_str = ""  # Additional main containers in same service

            # Color based on state
            if state == "running":
                state_str = f"{Colors.GREEN}{status}{Colors.RESET}"
            elif state == "exited":
                state_str = f"{Colors.RED}{status}{Colors.RESET}"
            else:
                state_str = f"{Colors.YELLOW}{status}{Colors.RESET}"

            # Format IP
            ip_str = ip if ip else f"{Colors.GRAY}-{Colors.RESET}"

            # Format ports
            ports = c.get("Publishers", []) or []
            port_strs = []
            for p in ports:
                if p.get("PublishedPort"):
                    port_strs.append(f"{p.get('PublishedPort')}:{p.get('TargetPort')}")
            ports_str = ", ".join(port_strs) if port_strs else f"{Colors.GRAY}-{Colors.RESET}"

            # Gray out dependency container names
            if is_dependency:
                container_name = f"{Colors.GRAY}{container_name}{Colors.RESET}"

            table.add_row([svc_str, container_name, state_str, ip_str, ports_str])

    print()
    print(table.render())

    # Summary
    print(f"\n{Colors.GREEN}{running_containers}{Colors.RESET}/{total_containers} container(s) running")

    return 0
