"""Upgrade command — trigger image updates via watchtower's HTTP API.

Exposes two flows:

- **Trigger** (`kompose upgrade [service]`): synchronously POSTs to
  `<watchtower>/v1/update`. While waiting, a background thread tails
  `docker logs -f watchtower --since <t0>`, filters for the high-signal
  events (Pulling / Stopping / Creating / Started / Removed image), and
  renders them compactly. The HTTP response's JSON report is used as the
  authoritative final summary.

- **Read-only logs** (`kompose upgrade --logs`): parses
  `docker logs watchtower` and slices the most recent session — between the
  last "Received HTTP API update request" / "Running update on schedule"
  trigger and the matching "Update session completed". No HTTP call.

Resolution & config:
  - Token  → `<host>/watchtower/.env::WATCHTOWER_HTTP_API_TOKEN`
  - URL    → `kompose.watchtower.url` (.kompose/rules.yaml) if set,
             else derive from `<host>/watchtower/compose.yml`
             (`services.watchtower.networks.reverse-proxy.ipv4_address`
             + port 8080 default).

Exit codes:
  0    success (Failed == 0)
  1    partial (Failed > 0)
  2    trigger failed (no token, no URL, HTTP non-2xx, network error)
  130  Ctrl+C during local tail (update may still complete on watchtower)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ._engine import load_kompose_config
from .config import get_host_dir
from .env import parse_env_file
from .utils import Colors, confirm

WATCHTOWER_SERVICE = "watchtower"
WATCHTOWER_DEFAULT_PORT = 8080
WATCHTOWER_DEFAULT_NETWORK = "reverse-proxy"
WATCHTOWER_CONTAINER_NAME = "watchtower"

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_TRIGGER_FAILED = 2
EXIT_INTERRUPTED = 130


# ---------------------------------------------------------------------------
# Config / discovery
# ---------------------------------------------------------------------------


def read_watchtower_token(host: str | None) -> str | None:
    """Return the bearer token from `<host>/watchtower/.env`, or None."""
    env_path = get_host_dir(host) / WATCHTOWER_SERVICE / ".env"
    if not env_path.exists():
        return None
    values = parse_env_file(env_path)
    raw = values.get("WATCHTOWER_HTTP_API_TOKEN", "")
    return _strip_env_quotes(raw) or None


def _strip_env_quotes(value: str) -> str:
    """Strip a single layer of matching single/double quotes from .env values."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def discover_watchtower_url(host: str | None) -> str | None:
    """Resolve the watchtower base URL (no trailing slash).

    Precedence:
      1. `kompose.watchtower.url` override in .kompose/rules.yaml
      2. derive from `<host>/watchtower/compose.yml` —
         `services.watchtower.networks.<net>.ipv4_address` + port 8080
    """
    config = load_kompose_config(host).get("watchtower") or {}
    if "url" in config and config["url"]:
        return config["url"].rstrip("/")

    compose_path = get_host_dir(host) / WATCHTOWER_SERVICE / "compose.yml"
    if not compose_path.exists():
        return None
    try:
        parsed = yaml.safe_load(compose_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return None

    svc = (parsed.get("services") or {}).get(WATCHTOWER_SERVICE) or {}
    networks = svc.get("networks") or {}
    # The fixed-IP layout uses a mapping under the network name (preferred);
    # fall back to scanning all attached networks for the first ipv4_address.
    net = networks.get(WATCHTOWER_DEFAULT_NETWORK) if isinstance(networks, dict) else None
    ip = None
    if isinstance(net, dict):
        ip = net.get("ipv4_address")
    if not ip and isinstance(networks, dict):
        for entry in networks.values():
            if isinstance(entry, dict) and entry.get("ipv4_address"):
                ip = entry["ipv4_address"]
                break
    if not ip:
        return None

    port = (config.get("port") if isinstance(config, dict) else None) or WATCHTOWER_DEFAULT_PORT
    return f"http://{ip}:{port}"


# ---------------------------------------------------------------------------
# Image extraction
# ---------------------------------------------------------------------------


@dataclass
class ImageResolution:
    """Result of resolving a service target into image names for the API."""
    target: str | None         # None when targeting all services
    images: list[str]          # sorted, deduped; empty for "all"


def _is_digest_pinned(image_ref: str) -> bool:
    return "@sha256:" in image_ref


def extract_images_from_compose(compose_path: Path) -> list[str]:
    """Return unique updatable images from a compose.yml.

    Skips services without an `image:` (build-only) and those pinned by digest
    (`@sha256:…`) since watchtower can't update those.
    """
    try:
        parsed = yaml.safe_load(compose_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return []
    services = parsed.get("services") or {}
    seen: set[str] = set()
    out: list[str] = []
    for svc_def in services.values():
        if not isinstance(svc_def, dict):
            continue
        image = svc_def.get("image")
        if not image or not isinstance(image, str):
            continue
        if _is_digest_pinned(image):
            continue
        if image in seen:
            continue
        seen.add(image)
        out.append(image)
    return sorted(out)


def resolve_target(host: str | None, service: str | None) -> ImageResolution:
    """Expand a CLI `service` argument to the list of images to pass to watchtower.

    - None / empty → full update (no filter).
    - A group dir → expand `<host>/<service>/compose.yml` to its images.
    - Anything else → error (no clean way to map a docker service name to an
      image without scanning every compose file; if you hit this in practice
      and want it, we'll add it then).
    """
    if not service:
        return ImageResolution(target=None, images=[])

    compose_path = get_host_dir(host) / service / "compose.yml"
    if not compose_path.exists():
        raise FileNotFoundError(
            f"Service '{service}' not found at {compose_path}"
        )
    images = extract_images_from_compose(compose_path)
    return ImageResolution(target=service, images=images)


# ---------------------------------------------------------------------------
# Watchtower log parsing (Pretty format from logrus)
# ---------------------------------------------------------------------------


_ANSI_RE = re.compile(r"\x1B\[[0-9;]*m")
_LOG_LINE_RE = re.compile(r"^(?P<level>[A-Z]{4})\[(?P<elapsed>\d+)\]\s+(?P<rest>.*)$")
_KV_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_.-]*)=("(?:[^"\\]|\\.)*"|\S+)')

_SESSION_START_MARKERS = (
    "Received HTTP API update request",
    "Running update on schedule",
    "Trying to load",  # cron tick — defensive
)
_SESSION_END_MARKER = "Update session completed"


@dataclass
class LogEvent:
    """A parsed watchtower log line — kept agnostic of formatting."""
    level: str        # INFO / DEBU / WARN / ERRO
    message: str      # e.g. "Pulling new image"
    fields: dict      # parsed key=value tail


def parse_watchtower_line(raw: str) -> LogEvent | None:
    """Parse one watchtower log line. Returns None for unparseable lines."""
    stripped = _ANSI_RE.sub("", raw).rstrip()
    if not stripped:
        return None
    match = _LOG_LINE_RE.match(stripped)
    if not match:
        return None
    rest = match.group("rest")
    # The message is the run of text before the first key=value pair (if any).
    kv_match = _KV_RE.search(rest)
    if kv_match:
        message = rest[: kv_match.start()].strip()
        kv_text = rest[kv_match.start() :]
    else:
        message = rest.strip()
        kv_text = ""
    fields = {k: v.strip('"') for k, v in _KV_RE.findall(kv_text)}
    return LogEvent(level=match.group("level"), message=message, fields=fields)


def slice_latest_session(lines: list[str]) -> list[LogEvent]:
    """Return the events of the most recent session.

    Walks from the end to find the most recent end marker (or last line if a
    session is in progress), then back to the matching start marker. Returns
    parsed events in chronological order.
    """
    events = [ev for ev in (parse_watchtower_line(line) for line in lines) if ev]
    if not events:
        return []

    # Find the most recent end (or fall through to "still running").
    end_idx = -1
    for i in range(len(events) - 1, -1, -1):
        if _SESSION_END_MARKER in events[i].message:
            end_idx = i
            break

    # Find the matching start, walking backward from end_idx (or last event).
    search_upper = end_idx if end_idx >= 0 else len(events) - 1
    start_idx = 0
    for i in range(search_upper, -1, -1):
        if any(marker in events[i].message for marker in _SESSION_START_MARKERS):
            start_idx = i
            break

    return events[start_idx : (end_idx + 1 if end_idx >= 0 else len(events))]


# ---------------------------------------------------------------------------
# Event rendering — concise output for both live tail and --logs
# ---------------------------------------------------------------------------


# Map of (level, message-prefix) → (icon, formatter). Order matters: first match wins.
_RENDERED_EVENTS: list[tuple[str, str, str]] = [
    ("Received HTTP API update", f"{Colors.CYAN}→{Colors.RESET}", "triggered via HTTP API"),
    ("Running update on schedule", f"{Colors.CYAN}→{Colors.RESET}", "triggered by schedule"),
    ("Pulling", f"{Colors.BLUE}⬇{Colors.RESET}", "pulling"),
    ("Found new", f"{Colors.YELLOW}⚑{Colors.RESET}", "new image"),
    ("Stopping container", f"{Colors.GRAY}⏸{Colors.RESET}", "stopping"),
    ("Creating new container", f"{Colors.GRAY}+{Colors.RESET}", "creating"),
    ("Started new container", f"{Colors.GREEN}▶{Colors.RESET}", "started"),
    ("Removed image", f"{Colors.GRAY}🗑{Colors.RESET}", "cleaned up image"),
    ("Update session completed", f"{Colors.BOLD}■{Colors.RESET}", "session done"),
]


def render_event(event: LogEvent) -> str | None:
    """Return a one-line rendering of a notable event, or None to skip."""
    if event.level not in ("INFO", "WARN", "ERRO"):
        return None
    for prefix, icon, label in _RENDERED_EVENTS:
        if event.message.startswith(prefix):
            return _format_event(event, icon, label)
    if event.level in ("WARN", "ERRO"):
        # Surface unknown warnings/errors verbatim.
        color = Colors.YELLOW if event.level == "WARN" else Colors.RED
        return f"  {color}!{Colors.RESET} {event.message} {_render_kv(event.fields)}".rstrip()
    return None


def _format_event(event: LogEvent, icon: str, label: str) -> str:
    target = event.fields.get("container") or event.fields.get("image") or ""
    detail = f" {Colors.GRAY}{target}{Colors.RESET}" if target else ""
    if "session" in label:
        scanned = event.fields.get("scanned", "?")
        updated = event.fields.get("updated", "?")
        failed = event.fields.get("failed", "?")
        return (
            f"  {icon} {label} "
            f"{Colors.GREEN}{updated} updated{Colors.RESET} · "
            f"{Colors.RED}{failed} failed{Colors.RESET} · "
            f"{Colors.GRAY}{scanned} scanned{Colors.RESET}"
        )
    return f"  {icon} {label}{detail}"


def _render_kv(fields: dict) -> str:
    if not fields:
        return ""
    return " ".join(f"{Colors.GRAY}{k}={Colors.RESET}{v}" for k, v in fields.items())


# ---------------------------------------------------------------------------
# HTTP trigger
# ---------------------------------------------------------------------------


@dataclass
class TriggerResult:
    """Outcome of the synchronous /v1/update call."""
    http_status: int
    body: dict | None         # parsed JSON, or None if not JSON
    error: str | None = None  # network / protocol error message


def trigger_update(url: str, token: str, images: list[str], timeout: float = 1800.0) -> TriggerResult:
    """POST /v1/update [?image=…] with a Bearer token. Synchronous (blocks until end)."""
    qs = ""
    if images:
        qs = "?" + urllib.parse.urlencode([("image", img) for img in images])
    request = urllib.request.Request(
        f"{url}/v1/update{qs}",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body_text = resp.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(body_text) if body_text else None
            except json.JSONDecodeError:
                body = None
            return TriggerResult(http_status=resp.status, body=body)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            body = json.loads(body_text) if body_text else None
        except json.JSONDecodeError:
            body = None
        return TriggerResult(http_status=e.code, body=body, error=str(e))
    except urllib.error.URLError as e:
        return TriggerResult(http_status=0, body=None, error=str(e.reason))
    except (OSError, TimeoutError) as e:
        return TriggerResult(http_status=0, body=None, error=str(e))


# ---------------------------------------------------------------------------
# Live log tail (background thread during a sync HTTP call)
# ---------------------------------------------------------------------------


class WatchtowerLogTail:
    """Background `docker logs -f watchtower --since <ts>` reader.

    Renders relevant events as they arrive. Started before the HTTP call,
    stopped after it returns. Honors Ctrl+C by setting an internal flag —
    the foreground exits cleanly while the daemon continues on watchtower.
    """

    def __init__(self, since: datetime):
        self.since = since
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        since_str = self.since.astimezone(timezone.utc).isoformat(timespec="seconds")
        self._proc = subprocess.Popen(
            ["docker", "logs", "-f", "--since", since_str, WATCHTOWER_CONTAINER_NAME],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
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
                if self._stop.is_set():
                    return
                event = parse_watchtower_line(line)
                if event is None:
                    continue
                rendered = render_event(event)
                if rendered:
                    print(rendered, flush=True)
        except Exception:
            return

    def stop(self) -> None:
        self._stop.set()
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
# Summary rendering
# ---------------------------------------------------------------------------


def _extract_summary(body: dict | None) -> tuple[int, int, int]:
    """Pull (updated, failed, skipped) out of the API JSON, with safe defaults."""
    if not isinstance(body, dict):
        return 0, 0, 0

    # The /v1/update response wraps a `metric` block; older builds inlined it.
    metric = body.get("metric") if isinstance(body.get("metric"), dict) else body
    updated = int(metric.get("updated", 0) or 0)
    failed = int(metric.get("failed", 0) or 0)
    scanned = int(metric.get("scanned", 0) or 0)
    skipped = scanned - updated - failed
    return updated, failed, max(skipped, 0)


def render_summary(result: TriggerResult) -> None:
    updated, failed, skipped = _extract_summary(result.body)
    print()
    print(
        f"{Colors.BOLD}Result:{Colors.RESET} "
        f"{Colors.GREEN}{updated} updated{Colors.RESET} · "
        f"{Colors.RED}{failed} failed{Colors.RESET} · "
        f"{Colors.GRAY}{skipped} skipped{Colors.RESET}"
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_upgrade(args) -> int:
    """Trigger an update via watchtower, or render the latest session with --logs."""
    host = getattr(args, "host", None)

    if getattr(args, "logs", False):
        return _cmd_upgrade_logs(host)

    service = getattr(args, "service", None)
    force = getattr(args, "force", False)

    try:
        resolution = resolve_target(host, service)
    except FileNotFoundError as e:
        print(f"{Colors.RED}Error: {e}{Colors.RESET}")
        return EXIT_TRIGGER_FAILED

    # A targeted service with zero updatable images is a silent no-op — nothing
    # to send to watchtower (all build-only or digest-pinned). Surface it.
    if resolution.target and not resolution.images:
        print(
            f"{Colors.YELLOW}No updatable images in '{resolution.target}' "
            f"(only build-only or digest-pinned services).{Colors.RESET}"
        )
        return EXIT_OK

    url = discover_watchtower_url(host)
    token = read_watchtower_token(host)
    if not url:
        print(
            f"{Colors.RED}Error: cannot resolve watchtower URL.{Colors.RESET}\n"
            f"Either add `kompose.watchtower.url` in `<host>/.kompose/rules.yaml`,\n"
            f"or ensure `<host>/watchtower/compose.yml` defines an `ipv4_address`."
        )
        return EXIT_TRIGGER_FAILED
    if not token:
        print(
            f"{Colors.RED}Error: WATCHTOWER_HTTP_API_TOKEN not found in "
            f"`<host>/watchtower/.env`.{Colors.RESET}"
        )
        return EXIT_TRIGGER_FAILED

    # Confirm only on the global (untargeted) form.
    if not resolution.target and not force:
        n = len(resolution.images) or "all"
        if not confirm(f"Trigger watchtower update on {n} containers?"):
            print(f"{Colors.GRAY}Aborted.{Colors.RESET}")
            return EXIT_OK

    label = resolution.target or "all containers"
    img_count = f" ({len(resolution.images)} image{'s' if len(resolution.images) != 1 else ''})" \
        if resolution.images else ""
    print(f"{Colors.BOLD}↻ Upgrading {label}{img_count}{Colors.RESET}")
    print(f"  {Colors.GRAY}{url}/v1/update{Colors.RESET}")

    # Capture t0 just before the trigger so the tail catches the first log line.
    t0 = datetime.now(timezone.utc)
    tail = WatchtowerLogTail(since=t0)
    tail.start()
    # Give the docker logs subprocess a moment to attach before the HTTP call,
    # otherwise the early "Received HTTP API update request" line is missed.
    time.sleep(0.5)

    try:
        result = trigger_update(url, token, resolution.images)
    except KeyboardInterrupt:
        tail.stop()
        print(f"\n{Colors.YELLOW}Interrupted locally — watchtower may still finish.{Colors.RESET}")
        return EXIT_INTERRUPTED
    finally:
        # The "Update session completed" line arrives slightly after the HTTP
        # response on some builds — give the tail a brief window to flush it
        # before we tear it down.
        time.sleep(0.8)
        tail.stop()

    if not (200 <= result.http_status < 300):
        detail = result.error or (result.body and json.dumps(result.body)) or ""
        print(
            f"\n{Colors.RED}Trigger failed: HTTP {result.http_status}{Colors.RESET}"
            + (f" — {detail}" if detail else "")
        )
        return EXIT_TRIGGER_FAILED

    render_summary(result)
    _updated, failed, _skipped = _extract_summary(result.body)
    return EXIT_PARTIAL if failed > 0 else EXIT_OK


def _cmd_upgrade_logs(host: str | None) -> int:
    """Render the latest watchtower session from `docker logs`. No trigger."""
    # The trailing newlines in docker logs are kept so the parser sees them
    # as line boundaries; --tail is generous (DEBUG mode is chatty).
    try:
        proc = subprocess.run(
            ["docker", "logs", "--tail", "5000", WATCHTOWER_CONTAINER_NAME],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"{Colors.RED}Error: failed to read watchtower logs: {e}{Colors.RESET}")
        return EXIT_TRIGGER_FAILED

    if proc.returncode != 0:
        print(f"{Colors.RED}Error: docker logs returned {proc.returncode}{Colors.RESET}")
        if proc.stderr:
            print(proc.stderr.strip())
        return EXIT_TRIGGER_FAILED

    lines = (proc.stdout + proc.stderr).splitlines()
    events = slice_latest_session(lines)
    if not events:
        print(f"{Colors.GRAY}No watchtower session found in recent logs.{Colors.RESET}")
        return EXIT_OK

    print(f"{Colors.BOLD}Latest watchtower session{Colors.RESET}")
    for event in events:
        rendered = render_event(event)
        if rendered:
            print(rendered)
    return EXIT_OK


__all__ = [
    "cmd_upgrade",
    "discover_watchtower_url",
    "read_watchtower_token",
    "extract_images_from_compose",
    "resolve_target",
    "parse_watchtower_line",
    "slice_latest_session",
    "render_event",
    "trigger_update",
    "ImageResolution",
    "LogEvent",
    "TriggerResult",
    "EXIT_OK",
    "EXIT_PARTIAL",
    "EXIT_TRIGGER_FAILED",
    "EXIT_INTERRUPTED",
]
