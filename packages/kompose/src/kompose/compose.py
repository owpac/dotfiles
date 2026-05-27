"""Docker Compose commands (up, down, restart, logs, status).

Two execution modes, auto-selected per command invocation:

- **Root mode** — when `<host>/compose.yml` exists at the host root. All
  services are unified under a single Docker Compose project via `include:`.
  Commands target this root file; service args are passed positionally to
  docker compose. Arg expansion: if an arg matches a service dir (group),
  it is expanded to all services declared in that group's compose.yml.

- **Legacy mode** — when no root compose.yml exists. Per-service iteration
  with optional layering of `base/<service>/compose.yml` + `<host>/<service>/compose.yml`.
  Preserved for hosts that have not adopted the include model.
"""

import re
import subprocess
import sys
from pathlib import Path

import yaml

from .config import WORKSPACE_DIR, get_base_dir, get_host_dir, get_services
from .utils import Colors, Table


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


# ---------------------------------------------------------------------------
# Status (info-only, doesn't mutate state)
# ---------------------------------------------------------------------------


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


def _parse_exposed_ports(ports_str: str) -> list[str]:
    """Extract listed ports from docker ps Ports column.

    Captures both exposed-only entries (e.g. `2283/tcp`) and the target port of
    published entries (e.g. `0.0.0.0:8080->80/tcp` → `80/tcp`). Returns a
    deduplicated list of `<port|range>/<proto>` strings in original order.

    Input examples:
      `0.0.0.0:8080->80/tcp, :::8080->80/tcp`        → ['80/tcp']
      `53/udp, 53/tcp, 80/tcp`                       → ['53/udp', '53/tcp', '80/tcp']
      `8324/tcp, 32412-32414/udp, 32400/tcp`         → ['8324/tcp', '32412-32414/udp', '32400/tcp']
    """
    if not ports_str:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for entry in ports_str.split(","):
        entry = entry.strip()
        if not entry:
            continue
        # Published port has the form `<ip>:<port>-><port|range>/<proto>` — take the right side.
        if "->" in entry:
            entry = entry.split("->", 1)[1].strip()
        if entry and entry not in seen:
            seen.add(entry)
            out.append(entry)
    return out


def _format_ports(ports: list[str], limit: int = 4) -> str:
    """Format a list of exposed ports for the status table (top `limit` + `+N`)."""
    if not ports:
        return f"{Colors.GRAY}-{Colors.RESET}"
    visible = ports[:limit]
    remaining = len(ports) - limit
    rendered = ", ".join(visible)
    if remaining > 0:
        rendered += f" {Colors.GRAY}+{remaining}{Colors.RESET}"
    return rendered


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
                project = ""
                service = ""
                for part in data.get("Labels", "").split(","):
                    if part.startswith("com.docker.compose.project="):
                        project = part.split("=", 1)[1]
                    elif part.startswith("com.docker.compose.service="):
                        service = part.split("=", 1)[1]
                containers.append({
                    "Name": data.get("Names", ""),
                    "State": data.get("State", ""),
                    "Status": data.get("Status", ""),
                    "ExposedPorts": _parse_exposed_ports(data.get("Ports", "")),
                    "_project": project,
                    "_service": service,
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
                    parts = line.split()
                    return float(parts[1]) * 1024  # kB to bytes
    except Exception:
        pass
    return 0


def _format_memory(mem_str: str, system_mem: float) -> str:
    """Format memory string as colored percentage."""
    try:
        parts = mem_str.split(" / ")
        if len(parts) != 2:
            return mem_str

        usage_str = parts[0].strip()
        limit_str = parts[1].strip()

        usage = _parse_mem_value(usage_str)
        limit = _parse_mem_value(limit_str)

        has_custom_limit = limit < (system_mem * 0.9) if system_mem > 0 else False

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
            pct = 0

        pct_str = f"{pct:.1f}%" if pct < 10 else f"{pct:.0f}%"
        if has_custom_limit:
            limit_compact = _compact_mem(limit)
            return f"{color}{pct_str}/{limit_compact}{Colors.RESET}"
        else:
            return f"{color}{pct_str}{Colors.RESET}"
    except Exception:
        return mem_str


def _format_cpu(cpu_perc_str: str) -> str:
    """Format CPU percentage with thresholds: <50% green, 50-100% yellow, >100% red.

    Input from docker stats is `% of one core` (so 100% = 1 core saturated,
    200% = 2 cores, etc.). We keep that semantic — raw value, just colorized.
    """
    try:
        pct = float(cpu_perc_str.rstrip("%").strip())
    except (ValueError, AttributeError):
        return cpu_perc_str or f"{Colors.GRAY}-{Colors.RESET}"

    if pct >= 100:
        color = Colors.RED
    elif pct >= 50:
        color = Colors.YELLOW
    else:
        color = Colors.GREEN

    pct_str = f"{pct:.1f}%" if pct < 10 else f"{pct:.0f}%"
    return f"{color}{pct_str}{Colors.RESET}"


# ---------------------------------------------------------------------------
# Stats source: snapshot (one-shot) vs streaming (live `-f` mode)
# ---------------------------------------------------------------------------


class StatsSource:
    """Interface — returns the latest stats dict for a container, or {} if absent."""

    def get(self, name: str) -> dict:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SnapshotStats(StatsSource):
    """One-shot `docker stats --no-stream` fetch."""

    def __init__(self):
        self._data: dict[str, dict] = {}

    def load(self) -> None:
        import json
        cmd = ["docker", "stats", "--no-stream", "--format", "{{json .}}"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    name = data.get("Name", "")
                    if name:
                        self._data[name] = data
                except json.JSONDecodeError:
                    continue
        except Exception:
            return

    def get(self, name: str) -> dict:
        return self._data.get(name, {})


class StreamingStats(StatsSource):
    """Background subprocess streaming `docker stats` updates.

    `docker stats` (without --no-stream) emits one JSON line per container
    roughly every second. A reader thread keeps `self.latest[name]` updated
    with the freshest payload. Render loops just read from memory.
    """

    def __init__(self):
        self.latest: dict[str, dict] = {}
        self._proc: subprocess.Popen | None = None
        self._thread: "threading.Thread | None" = None

    def start(self) -> None:
        import threading
        self._proc = subprocess.Popen(
            ["docker", "stats", "--format", "{{json .}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        import json
        if self._proc is None or self._proc.stdout is None:
            return
        try:
            for line in self._proc.stdout:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    name = data.get("Name", "")
                    if name:
                        self.latest[name] = data
                except json.JSONDecodeError:
                    continue
        except Exception:
            return

    def get(self, name: str) -> dict:
        return self.latest.get(name, {})

    def close(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None


def _build_status_table(
    sorted_services: list[tuple[str, list[dict]]],
    *,
    show_stats: bool,
    stats_source: StatsSource | None,
    system_mem_str: str,
    system_mem: float = 0,
) -> tuple[str, int, int]:
    """Render the status table to a string. Returns (text, total, running)."""
    headers = ["Service", "Container", "Status", "IP"]
    if show_stats:
        headers.append("CPU")
        headers.append(f"Mem ({system_mem_str})")
    headers.append("Ports")
    table = Table(headers)
    total_containers = 0
    running_containers = 0

    max_svc_len = max(len(svc) for svc, _ in sorted_services) if sorted_services else 0

    for service_name, containers in sorted_services:
        containers.sort(key=lambda c: (
            not c.get("_ip"),
            parse_ip_for_sort(c.get("_ip", "")),
            c.get("Name", ""),
        ))

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

            is_dependency = not ip and has_main_with_ip

            if first_in_group:
                svc_str = service_name
                first_in_group = False
            elif is_dependency:
                svc_str = f"{Colors.GRAY}└{'─' * (max_svc_len - 1)}{Colors.RESET}"
            else:
                svc_str = ""

            if state == "running":
                state_str = f"{Colors.GREEN}{status}{Colors.RESET}"
            elif state == "exited":
                state_str = f"{Colors.RED}{status}{Colors.RESET}"
            else:
                state_str = f"{Colors.YELLOW}{status}{Colors.RESET}"

            ip_str = ip if ip else f"{Colors.GRAY}-{Colors.RESET}"
            ports_str = _format_ports(c.get("ExposedPorts") or [])

            if is_dependency:
                container_name_display = f"{Colors.GRAY}{container_name}{Colors.RESET}"
            else:
                container_name_display = container_name

            row = [svc_str, container_name_display, state_str, ip_str]
            if show_stats:
                stats = stats_source.get(container_name) if stats_source else {}
                cpu_perc = stats.get("CPUPerc", "")
                mem_usage = stats.get("MemUsage", "")
                cpu_str = _format_cpu(cpu_perc) if cpu_perc else f"{Colors.GRAY}-{Colors.RESET}"
                mem_str = _format_memory(mem_usage, system_mem) if mem_usage else f"{Colors.GRAY}-{Colors.RESET}"
                row.append(cpu_str)
                row.append(mem_str)
            row.append(ports_str)
            table.add_row(row)

    return table.render(), total_containers, running_containers


def _gather_status_groups(host: str | None, service_arg: str | None) -> tuple[list[tuple[str, list[dict]]], list]:
    """Collect & group containers for the status view. Pure (no stats fetch)."""
    from concurrent.futures import ThreadPoolExecutor

    services = get_services(host)
    if not services:
        return [], []

    service_to_group = build_service_to_group_map(host)
    service_dir_names = {s.name for s in services}

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_containers = pool.submit(_get_all_compose_containers)
        future_network = pool.submit(get_network_containers, "reverse-proxy")
        all_containers = future_containers.result()
        network_containers = future_network.result()

    service_groups: dict[str, list[dict]] = {}
    for container in all_containers:
        project = container.get("_project", "")
        svc_label = container.get("_service", "")
        group = service_to_group.get(svc_label) if service_to_group else project
        if not group or group not in service_dir_names:
            continue
        name = container.get("Name", "")
        container["_ip"] = network_containers.get(name, {}).get("ipv4", "")
        container["_service_dir"] = group
        service_groups.setdefault(group, []).append(container)

    if service_arg:
        if service_arg in service_groups:
            service_groups = {service_arg: service_groups[service_arg]}
        else:
            filtered: dict[str, list[dict]] = {}
            for group_name, conts in service_groups.items():
                matching = [c for c in conts if c.get("_service") == service_arg]
                if matching:
                    filtered[group_name] = matching
            service_groups = filtered

    def get_main_ip(containers: list[dict]) -> str:
        for c in containers:
            if c.get("_ip"):
                return c["_ip"]
        return ""

    sorted_services = sorted(
        service_groups.items(),
        key=lambda x: parse_ip_for_sort(get_main_ip(x[1]))
    )
    return sorted_services, services


def cmd_status(args) -> int:
    """Show status of services with IPs.

    - `kompose status`                    → snapshot table
    - `kompose status --stats`            → snapshot table + CPU/Mem columns
    - `kompose status --stats -f [-i N]`  → live mode, refresh every N seconds
    - `kompose status <svc>`              → filtered + tail logs (default 30)
    - `kompose status <svc> -f`           → filtered + follow logs
    """
    host = getattr(args, "host", None)
    service_arg = getattr(args, "service", None)
    follow = getattr(args, "follow", False)

    # Live mode: -f without a specific service arg → refresh-table loop.
    if follow and not service_arg:
        return _watch_status(args)

    # Snapshot mode.
    show_stats = getattr(args, "stats", False) or bool(service_arg)
    stats_source: StatsSource | None = None
    if show_stats:
        snap = SnapshotStats()
        snap.load()
        stats_source = snap

    return _render_status_once(args, host, service_arg, show_stats, stats_source, follow_logs=follow)


def _render_status_once(
    args,
    host: str | None,
    service_arg: str | None,
    show_stats: bool,
    stats_source: StatsSource | None,
    *,
    follow_logs: bool,
) -> int:
    """Render a single snapshot of the status table. Used by snapshot AND watch modes."""
    sorted_services, services = _gather_status_groups(host, service_arg)

    if not services:
        print(f"{Colors.YELLOW}No services found{Colors.RESET}")
        return 0

    if not sorted_services:
        if service_arg:
            print(f"{Colors.YELLOW}No containers found for '{service_arg}'{Colors.RESET}")
        else:
            print(f"{Colors.YELLOW}No containers found{Colors.RESET}")
        return 0

    system_mem = _get_system_memory() if show_stats else 0
    system_mem_str = _compact_mem(system_mem) if system_mem > 0 else "?"

    table_text, total, running = _build_status_table(
        sorted_services,
        show_stats=show_stats,
        stats_source=stats_source,
        system_mem_str=system_mem_str,
        system_mem=system_mem,
    )

    print()
    print(table_text)
    print(f"\n{Colors.GREEN}{running}{Colors.RESET}/{total} container(s) running")

    # Drill-down: tail logs of the targeted service.
    if service_arg and not getattr(args, "no_logs", False):
        tail = str(getattr(args, "tail", "30"))
        if get_root_compose(host):
            target_services = resolve_root_targets(host, service_arg, None)
            extra = ["--tail", tail]
            if follow_logs:
                extra.append("-f")
            print(f"\n{Colors.BOLD}──── {service_arg} logs (last {tail}{' + follow' if follow_logs else ''}) ────{Colors.RESET}")
            run_root_compose(host, "logs", target_services, extra)
        else:
            extra = ["--tail", tail]
            if follow_logs:
                extra.append("-f")
            print(f"\n{Colors.BOLD}──── {service_arg} logs (last {tail}{' + follow' if follow_logs else ''}) ────{Colors.RESET}")
            run_compose(service_arg, "logs", host, extra)

    return 0


def _watch_status(args) -> int:
    """Live refreshing status table (kompose status -f). Stats stream in background."""
    import time
    from datetime import datetime

    host = getattr(args, "host", None)
    interval = max(1, int(getattr(args, "interval", 2) or 2))
    show_stats = True  # live mode implies stats (otherwise why refresh?)

    streamer = StreamingStats()
    streamer.start()
    # Give the streamer ~1s to receive the first batch of samples before the first render.
    time.sleep(1.0)

    # Hide cursor + register cleanup
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    try:
        while True:
            # Clear screen + cursor home
            sys.stdout.write("\033[2J\033[H")

            now = datetime.now().strftime("%H:%M:%S")
            header = (
                f"{Colors.BOLD}kompose status --stats -f{Colors.RESET}  "
                f"{Colors.GRAY}refresh {interval}s · {now} · Ctrl+C to exit{Colors.RESET}"
            )
            print(header)

            _render_status_once(args, host, None, show_stats, streamer, follow_logs=False)

            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        print()  # newline after ^C
    finally:
        streamer.close()
        # Restore cursor
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
    return 0
