"""Status command — read-only view of compose-managed containers.

Layered as four sections, top-down by abstraction level:

  1. **Data fetchers**: raw `docker network inspect` / `docker ps` / `/proc/meminfo` calls.
  2. **Formatters**: pure functions that turn raw strings into display cells
     (ports, CPU%, memory %, IP-sortable tuples).
  3. **Stats sources**: `StatsSource` interface with snapshot (one-shot) and
     streaming (background `docker stats`) implementations.
  4. **Table + commands**: gather → build → render, plus the live `-f` watch loop
     that uses the terminal's alternate screen buffer (htop/vim style).

The status code is intentionally separate from `compose.py` because it doesn't
mutate state and has its own concerns (formatting, streaming, terminal control).
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .compose import (
    build_service_to_group_map,
    get_root_compose,
    resolve_root_targets,
    run_compose,
    run_root_compose,
)
from .config import get_services
from .utils import Colors, Table

REVERSE_PROXY_NETWORK = "reverse-proxy"
_UNSORTABLE_IP = (999, 999, 999, 999)


# ---------------------------------------------------------------------------
# Data fetchers — raw docker / OS calls, no formatting
# ---------------------------------------------------------------------------


def get_network_containers(network: str = REVERSE_PROXY_NETWORK) -> dict[str, dict]:
    """Get containers and their IPs from a docker network."""
    cmd = ["docker", "network", "inspect", network, "--format", "{{ json .Containers }}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return {}
        containers_data = json.loads(result.stdout.strip())
        containers = {}
        for info in containers_data.values():
            name = info.get("Name", "")
            containers[name] = {
                "ipv4": info.get("IPv4Address", "").split("/")[0],
                "ipv6": info.get("IPv6Address", "").split("/")[0],
            }
        return containers
    except Exception:
        return {}


def _get_all_compose_containers() -> list[dict]:
    """Get all compose-managed containers with a single docker ps call."""
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
            except json.JSONDecodeError:
                continue
            labels = dict(p.split("=", 1) for p in data.get("Labels", "").split(",") if "=" in p)
            containers.append({
                "Name": data.get("Names", ""),
                "State": data.get("State", ""),
                "Status": data.get("Status", ""),
                "ExposedPorts": _parse_exposed_ports(data.get("Ports", "")),
                "_project": labels.get("com.docker.compose.project", ""),
                "_service": labels.get("com.docker.compose.service", ""),
            })
        return containers
    except Exception:
        return []


def _get_system_memory() -> float:
    """Get total system memory in bytes (from /proc/meminfo; Linux only)."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return float(line.split()[1]) * 1024  # kB → bytes
    except Exception:
        pass
    return 0


# ---------------------------------------------------------------------------
# Formatters — pure string → cell, used by the table renderer
# ---------------------------------------------------------------------------


def parse_ip_for_sort(ip: str) -> tuple:
    """Parse an IPv4 string into a sortable tuple; empties sort last."""
    if not ip:
        return _UNSORTABLE_IP
    try:
        return tuple(int(p) for p in ip.split("."))
    except (ValueError, AttributeError):
        return _UNSORTABLE_IP


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
        # Published port: `<ip>:<port>-><port|range>/<proto>` — keep the right side.
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
    rendered = ", ".join(visible)
    remaining = len(ports) - limit
    if remaining > 0:
        rendered += f" {Colors.GRAY}+{remaining}{Colors.RESET}"
    return rendered


_MEM_UNITS = {
    "b": 1,
    "kib": 1024,
    "kb": 1000,
    "mib": 1024 ** 2,
    "mb": 1000 ** 2,
    "gib": 1024 ** 3,
    "gb": 1000 ** 3,
}


def _parse_mem_value(s: str) -> float:
    """Parse a memory value like '696.9MiB' to bytes. Returns 0 on parse failure."""
    match = re.match(r"([\d.]+)\s*(\w+)", s)
    if not match:
        return 0
    return float(match.group(1)) * _MEM_UNITS.get(match.group(2).lower(), 1)


def _compact_mem(bytes_val: float) -> str:
    """Convert bytes to a compact display string like '697 M' or '2.1 G'."""
    if bytes_val >= 1024 ** 3:
        val = bytes_val / (1024 ** 3)
        return f"{val:.0f} G" if val >= 10 else f"{val:.1f} G"
    if bytes_val >= 1024 ** 2:
        return f"{bytes_val / (1024 ** 2):.0f} M"
    if bytes_val >= 1024:
        return f"{bytes_val / 1024:.0f} K"
    return f"{bytes_val:.0f} B"


def _format_memory(mem_str: str, system_mem: float) -> str:
    """Format `<usage> / <limit>` from docker stats as a coloured percentage.

    Appends `/<limit>` only when the container declares a custom mem limit
    (i.e. limit < 90% of system memory).
    """
    try:
        parts = mem_str.split(" / ")
        if len(parts) != 2:
            return mem_str

        usage = _parse_mem_value(parts[0].strip())
        limit = _parse_mem_value(parts[1].strip())
        has_custom_limit = limit < (system_mem * 0.9) if system_mem > 0 else False

        if limit > 0:
            pct = (usage / limit) * 100
            color = Colors.RED if pct >= 80 else Colors.YELLOW if pct >= 50 else Colors.GREEN
        else:
            color = Colors.GREEN
            pct = 0

        pct_str = f"{pct:.1f}%" if pct < 10 else f"{pct:.0f}%"
        if has_custom_limit:
            return f"{color}{pct_str}/{_compact_mem(limit)}{Colors.RESET}"
        return f"{color}{pct_str}{Colors.RESET}"
    except Exception:
        return mem_str


def _format_cpu(cpu_perc_str: str) -> str:
    """Format CPU percentage. Input is `% of one core` from docker stats —
    100% = 1 core saturated, 200% = 2 cores, etc. We just colourise.

    Thresholds: <50% green, 50–100% yellow, >100% red.
    """
    try:
        pct = float(cpu_perc_str.rstrip("%").strip())
    except (ValueError, AttributeError):
        return cpu_perc_str or f"{Colors.GRAY}-{Colors.RESET}"

    color = Colors.RED if pct >= 100 else Colors.YELLOW if pct >= 50 else Colors.GREEN
    pct_str = f"{pct:.1f}%" if pct < 10 else f"{pct:.0f}%"
    return f"{color}{pct_str}{Colors.RESET}"


# ---------------------------------------------------------------------------
# Stats sources — snapshot (one-shot) vs streaming (live `-f` mode)
# ---------------------------------------------------------------------------


def _parse_stats_line(line: str) -> tuple[str, dict] | None:
    """Parse one `docker stats --format json` line into `(name, data)`, or None."""
    if not line.strip():
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    name = data.get("Name", "")
    return (name, data) if name else None


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
        cmd = ["docker", "stats", "--no-stream", "--format", "{{json .}}"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return
            for line in result.stdout.strip().split("\n"):
                parsed = _parse_stats_line(line)
                if parsed:
                    self._data[parsed[0]] = parsed[1]
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
        self._thread: threading.Thread | None = None

    def start(self) -> None:
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
        if self._proc is None or self._proc.stdout is None:
            return
        try:
            for line in self._proc.stdout:
                parsed = _parse_stats_line(line)
                if parsed:
                    self.latest[parsed[0]] = parsed[1]
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


# ---------------------------------------------------------------------------
# Table + render — gather containers, build the table, drill into a service
# ---------------------------------------------------------------------------


def _gather_status_groups(host: str | None, service_arg: str | None) -> tuple[list[tuple[str, list[dict]]], list]:
    """Collect & group containers for the status view. Pure (no stats fetch)."""
    services = get_services(host)
    if not services:
        return [], []

    service_to_group = build_service_to_group_map(host)
    service_dir_names = {s.name for s in services}

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_containers = pool.submit(_get_all_compose_containers)
        future_network = pool.submit(get_network_containers, REVERSE_PROXY_NETWORK)
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


def _dash() -> str:
    """Greyed `-` placeholder — built at call time so --no-color is honoured."""
    return f"{Colors.GRAY}-{Colors.RESET}"


def _state_cell(state: str, status: str) -> str:
    color = {"running": Colors.GREEN, "exited": Colors.RED}.get(state, Colors.YELLOW)
    return f"{color}{status}{Colors.RESET}"


def _svc_cell(service_name: str, *, first: bool, is_dependency: bool, max_len: int) -> str:
    if first:
        return service_name
    if is_dependency:
        return f"{Colors.GRAY}└{'─' * (max_len - 1)}{Colors.RESET}"
    return ""


def _stats_cells(name: str, stats_source: StatsSource | None, system_mem: float) -> list[str]:
    stats = stats_source.get(name) if stats_source else {}
    cpu = stats.get("CPUPerc", "")
    mem = stats.get("MemUsage", "")
    return [
        _format_cpu(cpu) if cpu else _dash(),
        _format_memory(mem, system_mem) if mem else _dash(),
    ]


def _status_row(
    c: dict,
    service_name: str,
    *,
    first: bool,
    is_dependency: bool,
    max_svc_len: int,
    show_stats: bool,
    stats_source: StatsSource | None,
    system_mem: float,
) -> list[str]:
    name = c.get("Name", "")
    ip = c.get("_ip", "")
    name_display = f"{Colors.GRAY}{name}{Colors.RESET}" if is_dependency else name
    row = [
        _svc_cell(service_name, first=first, is_dependency=is_dependency, max_len=max_svc_len),
        name_display,
        _state_cell(c.get("State", ""), c.get("Status", "")),
        ip if ip else _dash(),
    ]
    if show_stats:
        row += _stats_cells(name, stats_source, system_mem)
    row.append(_format_ports(c.get("ExposedPorts") or []))
    return row


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
        headers += ["CPU", f"Mem ({system_mem_str})"]
    headers.append("Ports")
    table = Table(headers)
    total = running = 0
    max_svc_len = max((len(s) for s, _ in sorted_services), default=0)

    for service_name, containers in sorted_services:
        containers.sort(key=lambda c: (
            not c.get("_ip"),
            parse_ip_for_sort(c.get("_ip", "")),
            c.get("Name", ""),
        ))
        has_main_with_ip = any(c.get("_ip") for c in containers)

        for i, c in enumerate(containers):
            total += 1
            if c.get("State") == "running":
                running += 1
            is_dep = not c.get("_ip") and has_main_with_ip
            table.add_row(_status_row(
                c, service_name,
                first=(i == 0),
                is_dependency=is_dep,
                max_svc_len=max_svc_len,
                show_stats=show_stats,
                stats_source=stats_source,
                system_mem=system_mem,
            ))

    return table.render(), total, running


def _render_drilldown_logs(host: str | None, service_arg: str, tail: str, follow: bool) -> None:
    """Tail the logs of a single drilled-down service (root or legacy mode)."""
    extra = ["--tail", tail]
    if follow:
        extra.append("-f")
    header = f"\n{Colors.BOLD}──── {service_arg} logs (last {tail}{' + follow' if follow else ''}) ────{Colors.RESET}"
    if get_root_compose(host):
        print(header)
        run_root_compose(host, "logs", resolve_root_targets(host, service_arg, None), extra)
    else:
        print(header)
        run_compose(service_arg, "logs", host, extra)


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
        msg = f"No containers found for '{service_arg}'" if service_arg else "No containers found"
        print(f"{Colors.YELLOW}{msg}{Colors.RESET}")
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

    if service_arg and not getattr(args, "no_logs", False):
        _render_drilldown_logs(host, service_arg, str(getattr(args, "tail", "30")), follow_logs)

    return 0


# ---------------------------------------------------------------------------
# Commands — snapshot, drill-down, live watch
# ---------------------------------------------------------------------------


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


def _watch_status(args) -> int:
    """Live refreshing status table (kompose status -f). Stats stream in background.

    Renders inside the terminal's *alternate screen buffer* (`\\033[?1049h`),
    the same technique `htop`/`vim`/`less` use. On exit, the original terminal
    content is restored — nothing from the live session pollutes the scrollback.
    Each frame is built in memory then written atomically to avoid mid-render
    flicker.
    """
    host = getattr(args, "host", None)
    interval = max(1, int(getattr(args, "interval", 2) or 2))
    show_stats = True  # live mode implies stats (otherwise why refresh?)

    streamer = StreamingStats()
    streamer.start()
    # Give the streamer ~1s to receive the first batch of samples before the first render.
    time.sleep(1.0)

    # Enter alternate screen buffer + hide cursor.
    sys.stdout.write("\033[?1049h\033[?25l")
    sys.stdout.flush()

    try:
        while True:
            now = datetime.now().strftime("%H:%M:%S")
            header = (
                f"{Colors.BOLD}kompose status --stats -f{Colors.RESET}  "
                f"{Colors.GRAY}refresh {interval}s · {now} · Ctrl+C to exit{Colors.RESET}"
            )

            # Capture the table render to a buffer so we can write the whole
            # frame atomically — no flicker from partial paints.
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                _render_status_once(args, host, None, show_stats, streamer, follow_logs=False)

            # Compose frame: cursor home → header → captured table → clear-to-end.
            frame = "\033[H" + header + "\n" + buf.getvalue() + "\033[J"
            sys.stdout.write(frame)
            sys.stdout.flush()

            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        streamer.close()
        # Show cursor + leave alternate screen buffer (restores prior content).
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()
    return 0
