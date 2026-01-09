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


def cmd_ps(args) -> int:
    """List running services."""
    host = getattr(args, "host", None)
    service = getattr(args, "service", None)

    if service:
        return run_compose(service, "ps", host)
    else:
        # Show ps for all services
        services = get_services(host)
        if not services:
            print(f"{Colors.YELLOW}No services found{Colors.RESET}")
            return 0

        # Collect all running containers
        all_containers = []
        for service_dir in services:
            compose_files = get_compose_files(service_dir.name, host)
            if not compose_files:
                continue

            cmd = build_compose_command(compose_files, "ps", ["--format", "json"])
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, cwd=WORKSPACE_DIR)
                if result.returncode == 0 and result.stdout.strip():
                    import json
                    for line in result.stdout.strip().split("\n"):
                        if line:
                            try:
                                container = json.loads(line)
                                container["_service_dir"] = service_dir.name
                                all_containers.append(container)
                            except json.JSONDecodeError:
                                pass
            except Exception:
                pass

        if not all_containers:
            print(f"{Colors.YELLOW}No running containers{Colors.RESET}")
            return 0

        # Build table
        table = Table(["Service", "Container", "Status", "Ports"])
        for c in sorted(all_containers, key=lambda x: (x.get("_service_dir", ""), x.get("Name", ""))):
            service_name = c.get("_service_dir", "")
            container_name = c.get("Name", "")
            state = c.get("State", "")
            status = c.get("Status", "")

            # Color based on state
            if state == "running":
                state_str = f"{Colors.GREEN}{status}{Colors.RESET}"
            elif state == "exited":
                state_str = f"{Colors.RED}{status}{Colors.RESET}"
            else:
                state_str = f"{Colors.YELLOW}{status}{Colors.RESET}"

            # Format ports
            ports = c.get("Publishers", []) or []
            port_strs = []
            for p in ports:
                if p.get("PublishedPort"):
                    port_strs.append(f"{p.get('PublishedPort')}:{p.get('TargetPort')}")
            ports_str = ", ".join(port_strs) if port_strs else f"{Colors.GRAY}-{Colors.RESET}"

            table.add_row([service_name, container_name, state_str, ports_str])

        print()
        print(table.render())
        print(f"\n{Colors.GRAY}{len(all_containers)} container(s){Colors.RESET}")
        return 0
