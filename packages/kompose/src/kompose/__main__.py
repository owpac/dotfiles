"""
Kompose - CLI for managing Docker Compose services.

Usage:
    kompose <command> [options]

Top-level (daily ergonomics):
    up           Start services             (alias: service up)
    down         Stop services              (alias: service down)
    restart   r  Restart services           (alias: service restart)
    logs      l  View service logs          (alias: service logs)
    status    st Show services status       (alias: service status)
    check        Lint compose files and env drift
    fix          Auto-fix (compose-level rules + interactive env sync)
                   --auto  : only compose-level auto-fixes
                   --env   : only interactive env sync
    upgrade      Trigger image updates via watchtower's HTTP API
                   --logs  : render the latest session, no trigger
    run          Run a per-service action from .kompose/commands.yaml
                   `kompose run`                  : list all actions
                   `kompose run <service>`        : list a service's actions
                   `kompose run <action>`         : auto-resolve and execute
                   `kompose run <svc> <action>`   : explicit form
                   `kompose run <action> -- ...`  : forward args verbatim

Canonical noun-verb form:
    service [svc] up|down|restart|logs|status

Per-subcommand argparse + zsh-completion plumbing lives in `kompose.cli.*`;
this module is just the assembler.
"""

import argparse
import sys

from kompose import __version__, cli
from kompose.cli import _shared
from kompose.config import DEFAULT_HOST
from kompose.utils import init_colors


_EPILOG = f"""
Examples:
  kompose up                    Start all services (host: {DEFAULT_HOST})
  kompose up paperless          Start a single service (or expand a group)
  kompose down servarr plex     Stop a specific container inside a group
  kompose restart immich        (alias: kompose r immich)
  kompose logs paperless -n 50  (alias: kompose l paperless -n 50)
  kompose st                    Rich table of all services (alias of `status`)
  kompose status traefik        Filtered table + last 30 log lines
  kompose status traefik -f     Same, follow logs continuously
  kompose check                 Run every lint rule (compose + env)
  kompose fix                   Apply all fixes (compose + interactive env sync)
  kompose fix --auto            Only compose-level auto-fixes (no env prompts)
  kompose fix --env             Only interactive env sync
  kompose fix --dry-run         Preview only
  kompose upgrade               Trigger watchtower update on every container
  kompose upgrade paperless     Same, scoped to one group's images
  kompose upgrade --logs        Show the latest watchtower session
  kompose run                   List all actions declared in commands.yaml
  kompose run crowdsec          List actions for one service
  kompose run hub-upgrade       Run an action (auto-resolves the service)
  kompose run crowdsec hub-upgrade
                                Explicit service+action form
  kompose run hub-upgrade -- --force
                                Forward args after `--` to the in-container cmd
  kompose service status        Canonical form of `kompose status`

Host override:
  kompose --host other up       Use different host directory
"""


# All cli.<name> modules registered at the top level. Order is the order of
# precedence for shtab's `--help` output. Each module exposes
# `register_top_level(subparsers)`.
_TOP_LEVEL_MODULES = (cli.compose, cli.status, cli.check, cli.fix, cli.upgrade, cli.run)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kompose",
        description="CLI for managing Docker Compose services",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EPILOG,
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    parser.add_argument(
        "--host", metavar="HOST", default=None,
        help=f"Host directory (default: {DEFAULT_HOST})",
    ).complete = _shared.COMPLETE_HOST
    parser.add_argument("--completion", choices=["zsh"], metavar="SHELL", help="Print a shell completion script to stdout and exit")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    for module in _TOP_LEVEL_MODULES:
        module.register_top_level(subparsers)

    cli.service.register(subparsers)

    return parser


def _full_zsh_preamble() -> str:
    """Concatenate the shared preamble with each cli module's optional snippet."""
    parts = [_shared.ZSH_PREAMBLE]
    for module in _TOP_LEVEL_MODULES:
        snippet = getattr(module, "ZSH_PREAMBLE", None)
        if snippet:
            parts.append(snippet)
    return "".join(parts)


def main() -> int:
    parser = _build_parser()

    raw_argv, forwarded = cli.run.split_forwarded_args(sys.argv[1:])
    args = parser.parse_args(raw_argv)
    args.forwarded = forwarded

    if args.completion:
        import shtab
        sys.stdout.write(shtab.complete(parser, shell=args.completion, preamble={"zsh": _full_zsh_preamble()}))
        return 0

    init_colors(args.no_color)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command in ("service", "svc") and getattr(args, "service_command", None) is None:
        # The `service` subparser is registered first by cli.service; re-fetch
        # it to show its help. We could cache it, but this path is cold.
        for action in parser._subparsers._actions:  # type: ignore[union-attr]
            if isinstance(action, argparse._SubParsersAction):
                action.choices["service"].print_help()
                return 0

    if hasattr(args, "func"):
        return args.func(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
