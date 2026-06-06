"""Per-service action runner: `kompose run [<service>] <action> [-- args]`.

Actions are user-defined shortcuts for `docker exec <container> sh -c '<cmd>'`,
declared in `<host>/.kompose/commands.yaml` (mono-mode) or
`<host>/.kompose/commands/<service>.yaml` (multi-mode), e.g.:

    services:
      crowdsec:
        actions:
          hub-upgrade: cscli hub upgrade        # short form (string)
          shell:                                # long form (object)
            exec: bash
            tty: true
      servarr:
        actions:
          sonarr-rescan:
            container: sonarr                   # override (default = service name)
            exec: sonarr-cli rescan

Lookup rules — `kompose run <a>` resolves <a> against all loaded actions; if a
single action across all services has that name it runs, otherwise we list the
candidates and bail. `kompose run <s> <a>` is the explicit, unambiguous form.

Pure logic only: schema, lookup, execution. CLI plumbing (subparser, zsh
completion, `--` separator handling) lives in `kompose.cli.run`.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from ._engine import get_kompose_dir
from .utils import Colors


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass
class Action:
    name: str
    service: str
    container: str
    exec: str
    tty: bool = False
    source: Path | None = None  # for error messages

    @property
    def qualified_name(self) -> str:
        return f"{self.service}:{self.name}"


def _parse_action(name: str, raw, service: str, source: Path) -> Action:
    """Parse one action entry — string (short form) or dict (long form)."""
    if isinstance(raw, str):
        return Action(name=name, service=service, container=service, exec=raw, source=source)
    if isinstance(raw, dict):
        exec_cmd = raw.get("exec")
        if not isinstance(exec_cmd, str) or not exec_cmd.strip():
            raise ValueError(
                f"{source}: action '{service}.{name}': long form requires a non-empty `exec:` string"
            )
        tty_raw = raw.get("tty", False)
        # Strict bool — guard against `tty: "false"` (a truthy string) silently
        # enabling TTY allocation. YAML's native `true`/`false` decode to bools.
        if not isinstance(tty_raw, bool):
            raise ValueError(
                f"{source}: action '{service}.{name}': `tty:` must be true or false, got {tty_raw!r}"
            )
        return Action(
            name=name,
            service=service,
            container=raw.get("container") or service,
            exec=exec_cmd,
            tty=tty_raw,
            source=source,
        )
    raise ValueError(
        f"{source}: action '{service}.{name}': value must be a string or a mapping, got {type(raw).__name__}"
    )


def _parse_services_block(data: dict, source: Path) -> list[Action]:
    """Walk `services: <svc>: actions: {…}` and yield Action objects."""
    services = data.get("services") or {}
    if not isinstance(services, dict):
        raise ValueError(f"{source}: top-level `services:` must be a mapping")
    actions: list[Action] = []
    for svc_name, svc_block in services.items():
        if not isinstance(svc_block, dict):
            continue
        action_block = svc_block.get("actions") or {}
        if not isinstance(action_block, dict):
            raise ValueError(f"{source}: services.{svc_name}.actions must be a mapping")
        for action_name, raw in action_block.items():
            actions.append(_parse_action(action_name, raw, svc_name, source))
    return actions


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_yaml_mapping(path: Path) -> dict:
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping at top level")
    return data


def _accept(action: Action, actions: list[Action], seen: dict[str, Path]) -> None:
    """Add an action to the accumulator, raising on duplicate qualified name."""
    if action.qualified_name in seen:
        raise ValueError(
            f"Duplicate action '{action.qualified_name}' "
            f"in {action.source} (already in {seen[action.qualified_name]})"
        )
    actions.append(action)
    seen[action.qualified_name] = action.source  # type: ignore[assignment]


def load_commands(host: str | None = None) -> list[Action]:
    """Load actions from `<host>/.kompose/commands.yaml` and/or commands/*.yaml.

    Mono-mode and multi-mode can coexist. Duplicate `<service>.<action>` raises.
    Returns `[]` if no file exists (so the CLI can still list "nothing").
    """
    kompose_dir = get_kompose_dir(host)
    actions: list[Action] = []
    seen: dict[str, Path] = {}

    mono = kompose_dir / "commands.yaml"
    if mono.exists():
        for action in _parse_services_block(_load_yaml_mapping(mono), mono):
            _accept(action, actions, seen)

    multi_dir = kompose_dir / "commands"
    if multi_dir.is_dir():
        for path in sorted(multi_dir.glob("*.yaml")):
            data = _load_yaml_mapping(path)
            # Per-service file: filename is the service name, `actions:` at top.
            # Otherwise we expect the full `services:` schema, like the mono file.
            if "actions" in data and "services" not in data:
                action_block = data["actions"] or {}
                if not isinstance(action_block, dict):
                    raise ValueError(f"{path}: actions must be a mapping")
                for action_name, raw in action_block.items():
                    _accept(_parse_action(action_name, raw, path.stem, path), actions, seen)
            else:
                for action in _parse_services_block(data, path):
                    _accept(action, actions, seen)

    return actions


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def resolve_action(
    actions: list[Action],
    first: str,
    second: str | None,
) -> Action:
    """Resolve a CLI invocation to a single Action.

    - second is None:  `first` is the action name (must be globally unique)
    - second is set:   `first` is the service, `second` is the action
    Raises LookupError with a helpful message on miss / ambiguity.
    """
    if second is not None:
        for a in actions:
            if a.service == first and a.name == second:
                return a
        raise LookupError(
            f"No action '{second}' on service '{first}'. "
            f"Available: {_list_actions_for(actions, first) or '(none)'}"
        )

    matches = [a for a in actions if a.name == first]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise LookupError(f"No action named '{first}' found in any service.")
    candidates = ", ".join(a.qualified_name for a in matches)
    raise LookupError(
        f"Action '{first}' is ambiguous (defined in: {candidates}). "
        f"Use the explicit form: kompose run <service> {first}"
    )


def _list_actions_for(actions: list[Action], service: str) -> str:
    names = sorted(a.name for a in actions if a.service == service)
    return ", ".join(names)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def build_docker_exec(action: Action, forward_args: list[str]) -> list[str]:
    """Build the docker exec argv. Args after `--` are appended to the shell string."""
    shell_cmd = action.exec
    if forward_args:
        # Quote each forwarded arg via printf-friendly single-quote escape so
        # the shell receives them intact.
        quoted = " ".join(_shell_quote(a) for a in forward_args)
        shell_cmd = f"{shell_cmd} {quoted}"
    flags = ["-i"]
    if action.tty and sys.stdin.isatty():
        flags = ["-it"]
    return ["docker", "exec", *flags, action.container, "sh", "-c", shell_cmd]


def _shell_quote(s: str) -> str:
    """Minimal POSIX shell quoting: wrap in single quotes, escape embedded ones."""
    if not s:
        return "''"
    return "'" + s.replace("'", "'\\''") + "'"


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


def _should_list_service(first: str, second: str | None, actions: list[Action]) -> bool:
    """True when a lone `kompose run <first>` should print the service's action list.

    Triggered only if `first` names a service that has actions AND no action
    elsewhere shares that name (in which case action-execution wins by intent).
    """
    if second is not None:
        return False
    matches_a_service = any(a.service == first for a in actions)
    matches_an_action = any(a.name == first for a in actions)
    return matches_a_service and not matches_an_action


def cmd_run(args) -> int:
    """`kompose run [<service>] [<action>] [-- <forwarded args...>]`."""
    host = getattr(args, "host", None)
    first = getattr(args, "first", None)
    second = getattr(args, "second", None)
    verbose = getattr(args, "verbose", False)
    forwarded = list(getattr(args, "forwarded", None) or [])

    try:
        actions = load_commands(host)
    except (ValueError, OSError) as e:
        print(f"{Colors.RED}Error loading commands: {e}{Colors.RESET}")
        print(f"{Colors.GRAY}Hint: run `kompose doctor --commands` for a structured report.{Colors.RESET}")
        return 2

    if first is None:
        return _print_list(actions, scope=None)

    if _should_list_service(first, second, actions):
        return _print_list(actions, scope=first)

    try:
        action = resolve_action(actions, first, second)
    except LookupError as e:
        print(f"{Colors.RED}{e}{Colors.RESET}")
        return 2

    cmd = build_docker_exec(action, forwarded)
    if verbose:
        # shlex.join only quotes args that need it (spaces, shell metachars),
        # so the output looks like a copy-pasteable shell command rather than
        # a wall of single quotes.
        print(f"{Colors.GRAY}+ {shlex.join(cmd)}{Colors.RESET}")
    try:
        return subprocess.run(cmd).returncode
    except KeyboardInterrupt:
        print()
        return 130


def _print_list(actions: list[Action], scope: str | None) -> int:
    """Print actions, optionally filtered to a single service."""
    if not actions:
        print(f"{Colors.YELLOW}No actions defined. Create <host>/.kompose/commands.yaml.{Colors.RESET}")
        return 0

    rows = [a for a in actions if scope is None or a.service == scope]
    if not rows:
        print(f"{Colors.YELLOW}No actions for service '{scope}'.{Colors.RESET}")
        return 0

    rows.sort(key=lambda a: (a.service, a.name))
    width = max(len(a.qualified_name) for a in rows)
    title = f"Actions for {scope}" if scope else "All actions"
    print(f"{Colors.BOLD}{title}{Colors.RESET}")
    for a in rows:
        qn = a.qualified_name.ljust(width)
        exec_preview = a.exec if len(a.exec) <= 60 else a.exec[:57] + "..."
        print(f"  {Colors.CYAN}{qn}{Colors.RESET}  {Colors.GRAY}{exec_preview}{Colors.RESET}")
    return 0
