"""Docker Compose commands (up, down, restart, logs, ps)."""

import re
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


def _parse_ports_string(ports_str: str) -> list[dict]:
    """Parse docker ps Ports string into Publishers-compatible format.

    Input: '0.0.0.0:8080->80/tcp, :::8080->80/tcp'
    Output: [{'PublishedPort': 8080, 'TargetPort': 80}]
    """
    if not ports_str:
        return []
    publishers = []
    seen = set()
    for match in re.finditer(r"(?:\d+\.[\d.]+):(\d+)->(\d+)", ports_str):
        published, target = match.groups()
        key = (published, target)
        if key not in seen:
            seen.add(key)
            publishers.append({"PublishedPort": int(published), "TargetPort": int(target)})
    return publishers


def _get_all_compose_containers() -> list[dict]:
    """Get all compose-managed containers with a single docker ps call."""
    import json

    cmd = ["docker", "ps", "-a", "--filter", "label=com.docker.compose.project", "--format", "json"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return []

        containers = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                # Extract compose project from labels
                project = ""
                for part in data.get("Labels", "").split(","):
                    if part.startswith("com.docker.compose.project="):
                        project = part.split("=", 1)[1]
                        break
                containers.append({
                    "Name": data.get("Names", ""),
                    "State": data.get("State", ""),
                    "Status": data.get("Status", ""),
                    "Publishers": _parse_ports_string(data.get("Ports", "")),
                    "_project": project,
                })
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


def _parse_mem_value(s: str) -> float:
    """Parse memory value like '696.9MiB' to bytes."""
    match = re.match(r"([\d.]+)\s*(\w+)", s)
    if not match:
        return 0
    
    value = float(match.group(1))
    unit = match.group(2).lower()
    
    multipliers = {
        "b": 1,
        "kib": 1024,
        "kb": 1000,
        "mib": 1024 * 1024,
        "mb": 1000 * 1000,
        "gib": 1024 * 1024 * 1024,
        "gb": 1000 * 1000 * 1000,
    }
    
    return value * multipliers.get(unit, 1)


def _compact_mem(bytes_val: float) -> str:
    """Convert bytes to compact string like '697M' or '2.1G'."""
    if bytes_val >= 1024 * 1024 * 1024:
        val = bytes_val / (1024 * 1024 * 1024)
        return f"{val:.0f} G" if val >= 10 else f"{val:.1f} G"
    elif bytes_val >= 1024 * 1024:
        val = bytes_val / (1024 * 1024)
        return f"{val:.0f} M"
    elif bytes_val >= 1024:
        val = bytes_val / 1024
        return f"{val:.0f} K"
    else:
        return f"{bytes_val:.0f} B"


def _get_system_memory() -> float:
    """Get total system memory in bytes."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    # Format: "MemTotal:       32456789 kB"
                    parts = line.split()
                    return float(parts[1]) * 1024  # kB to bytes
    except Exception:
        pass
    return 0


def _format_memory(mem_str: str, system_mem: float) -> str:
    """Format memory string with color based on usage percentage.
    
    Input: '696.9MiB / 31.12GiB'
    Output: colored '697 MiB' or '697M/2G' if custom limit
    """
    try:
        parts = mem_str.split(" / ")
        if len(parts) != 2:
            return mem_str
        
        usage_str = parts[0].strip()
        limit_str = parts[1].strip()
        
        usage = _parse_mem_value(usage_str)
        limit = _parse_mem_value(limit_str)
        
        # Check if this is a custom limit (significantly less than system memory)
        has_custom_limit = limit < (system_mem * 0.9) if system_mem > 0 else False
        
        # Calculate percentage for color
        if limit > 0:
            pct = (usage / limit) * 100
            if pct >= 80:
                color = Colors.RED
            elif pct >= 50:
                color = Colors.YELLOW
            else:
                color = Colors.GREEN
        else:
            color = Colors.GREEN
        
        # Format output
        if has_custom_limit:
            # Show compact format with limit: "697M/2G"
            usage_compact = _compact_mem(usage)
            limit_compact = _compact_mem(limit)
            return f"{color}{usage_compact}/{limit_compact}{Colors.RESET}"
        else:
            # Just show usage with space: "697 MiB"
            formatted = re.sub(r"(\d)([A-Za-z])", r"\1 \2", usage_str)
            return f"{color}{formatted}{Colors.RESET}"
    except Exception:
        return mem_str


def get_container_memory_stats(system_mem: float) -> dict[str, str]:
    """Get memory usage/limit for all running containers."""
    cmd = ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return {}

        stats = {}
        for line in result.stdout.strip().split("\n"):
            if line and "\t" in line:
                name, mem_usage = line.split("\t", 1)
                stats[name] = _format_memory(mem_usage, system_mem)
        return stats
    except Exception:
        return {}


def cmd_status(args) -> int:
    """Show status of all services with IPs."""
    from concurrent.futures import ThreadPoolExecutor

    host = getattr(args, "host", None)
    services = get_services(host)

    if not services:
        print(f"{Colors.YELLOW}No services found{Colors.RESET}")
        return 0

    # Get system memory for header and formatting
    system_mem = _get_system_memory()
    system_mem_str = _compact_mem(system_mem) if system_mem > 0 else "?"

    # Collect all data in parallel: 3 calls instead of N+2 sequential
    with ThreadPoolExecutor(max_workers=3) as pool:
        future_containers = pool.submit(_get_all_compose_containers)
        future_network = pool.submit(get_network_containers, "reverse-proxy")
        future_memory = pool.submit(get_container_memory_stats, system_mem)

        all_containers = future_containers.result()
        network_containers = future_network.result()
        memory_stats = future_memory.result()

    # Group containers by compose project, filtering to known services
    service_names = {s.name for s in services}
    service_groups: dict[str, list[dict]] = {}
    for container in all_containers:
        project = container.get("_project", "")
        if project not in service_names:
            continue
        name = container.get("Name", "")
        container["_ip"] = network_containers.get(name, {}).get("ipv4", "")
        container["_service_dir"] = project
        if project not in service_groups:
            service_groups[project] = []
        service_groups[project].append(container)

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

    # Build table with dynamic Mem header
    mem_header = f"Mem ({system_mem_str})"
    table = Table(["Service", "Container", "Status", "IP", mem_header, "Ports"])
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

            # Format memory (already colored)
            mem_str = memory_stats.get(container_name, f"{Colors.GRAY}-{Colors.RESET}")

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

            table.add_row([svc_str, container_name, state_str, ip_str, mem_str, ports_str])

    print()
    print(table.render())

    # Summary
    print(f"\n{Colors.GREEN}{running_containers}{Colors.RESET}/{total_containers} container(s) running")

    return 0
