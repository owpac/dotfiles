"""
Kompose - CLI for managing Docker Compose services.

Usage:
    kompose <command> [options]

Top-level (daily ergonomics):
    up           Start services             (alias: service up)
    down         Stop services              (alias: service down)
    restart      Restart services           (alias: service restart)
    logs         View service logs          (alias: service logs)
    status       Show services status       (alias: service status)
    check        Lint compose files and env drift
    fix          Auto-fix what can be fixed (today: env sync)

Canonical noun-verb forms:
    service up|down|restart|logs|status
    env fix
"""

import argparse
import sys

from kompose import __version__
from kompose.compose import cmd_down, cmd_logs, cmd_restart, cmd_status, cmd_up
from kompose.config import DEFAULT_HOST
from kompose.env import cmd_env_fix, cmd_fix
from kompose.lint import cmd_check
from kompose.utils import init_colors


# ---------------------------------------------------------------------------
# Arg helpers — keep the same shape for top-level aliases and canonical forms
# ---------------------------------------------------------------------------


def _add_lifecycle_args(parser: argparse.ArgumentParser) -> None:
    """Args shared by up/down/restart: <service> + <containers...>."""
    parser.add_argument("service", nargs="?", metavar="<service>", help="Service (group dir) or docker compose service name")
    parser.add_argument("containers", nargs="*", metavar="<container>", help="Specific containers within the service")


def _add_logs_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("service", metavar="<service>", help="Service to view logs")
    parser.add_argument("containers", nargs="*", metavar="<container>", help="Specific containers within the service")
    parser.add_argument("-f", "--follow", action="store_true", default=True, help="Follow log output (default)")
    parser.add_argument("--no-follow", action="store_false", dest="follow", help="Don't follow log output")
    parser.add_argument("-n", "--tail", default="100", metavar="N", help="Number of lines to show (default: 100)")


def _add_status_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("service", nargs="?", metavar="<service>", help="Drill into a specific service: filter the table and tail its logs")
    parser.add_argument("-s", "--stats", action="store_true", help="Show memory usage stats")
    parser.add_argument("-n", "--tail", default="30", metavar="N", help="Lines of log to show when drilling into a service (default: 30)")
    parser.add_argument("-f", "--follow", action="store_true", help="Follow logs after the tail (only meaningful with a service arg)")
    parser.add_argument("--no-logs", action="store_true", help="Suppress the log tail when drilling into a service")


def _add_check_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("service", nargs="?", metavar="<service>", help="Service to check (default: all)")


def _add_fix_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("service", nargs="?", metavar="<service>", help="Service to fix (default: all)")
    parser.add_argument("-f", "--force", action="store_true", help="Skip confirmation, apply defaults")
    parser.add_argument("--dry-run", action="store_true", help="Preview what would change without applying")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="kompose",
        description="CLI for managing Docker Compose services",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  kompose up                    Start all services (host: {DEFAULT_HOST})
  kompose up paperless          Start a single service (or expand a group)
  kompose down servarr plex     Stop a specific container inside a group
  kompose restart immich
  kompose logs paperless -n 50
  kompose status                Rich table of all services
  kompose status traefik        Filtered table + last 30 log lines
  kompose status traefik -f     Same, follow logs continuously
  kompose check                 Run every lint rule (compose + env)
  kompose fix                   Apply auto-fixes (today: env sync)
  kompose fix -f                Non-interactive fix
  kompose env fix paperless     Scoped env sync for one service
  kompose service status        Canonical form of `kompose status`

Host override:
  kompose --host other up       Use different host directory
""",
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    parser.add_argument("--host", metavar="HOST", default=None, help=f"Host directory (default: {DEFAULT_HOST})")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # ---- Top-level aliases (lifecycle) ----
    p = subparsers.add_parser("up", help="Start services (alias of: service up)")
    _add_lifecycle_args(p)
    p.set_defaults(func=cmd_up)

    p = subparsers.add_parser("down", help="Stop services (alias of: service down)")
    _add_lifecycle_args(p)
    p.set_defaults(func=cmd_down)

    p = subparsers.add_parser("restart", help="Restart services (alias of: service restart)")
    _add_lifecycle_args(p)
    p.set_defaults(func=cmd_restart)

    p = subparsers.add_parser("logs", help="View service logs (alias of: service logs)")
    _add_logs_args(p)
    p.set_defaults(func=cmd_logs)

    p = subparsers.add_parser("status", help="Show services status (alias of: service status)")
    _add_status_args(p)
    p.set_defaults(func=cmd_status)

    # ---- Top-level globals ----
    p = subparsers.add_parser("check", help="Lint compose files and env drift")
    _add_check_args(p)
    p.set_defaults(func=cmd_check)

    p = subparsers.add_parser("fix", help="Auto-fix what can be fixed (today: env sync)")
    _add_fix_args(p)
    p.set_defaults(func=cmd_fix)

    # ---- Canonical noun: service ----
    service_parser = subparsers.add_parser("service", help="Service lifecycle (canonical noun-verb form)")
    service_subparsers = service_parser.add_subparsers(dest="service_command", metavar="<verb>")

    sp = service_subparsers.add_parser("up", help="Start services")
    _add_lifecycle_args(sp)
    sp.set_defaults(func=cmd_up)

    sp = service_subparsers.add_parser("down", help="Stop services")
    _add_lifecycle_args(sp)
    sp.set_defaults(func=cmd_down)

    sp = service_subparsers.add_parser("restart", help="Restart services")
    _add_lifecycle_args(sp)
    sp.set_defaults(func=cmd_restart)

    sp = service_subparsers.add_parser("logs", help="View service logs")
    _add_logs_args(sp)
    sp.set_defaults(func=cmd_logs)

    sp = service_subparsers.add_parser("status", help="Show services status with IPs")
    _add_status_args(sp)
    sp.set_defaults(func=cmd_status)

    # ---- Canonical noun: env ----
    env_parser = subparsers.add_parser("env", help="Environment file operations")
    env_subparsers = env_parser.add_subparsers(dest="env_command", metavar="<verb>")

    ep = env_subparsers.add_parser("fix", help="Interactive .env / .env.example sync")
    _add_fix_args(ep)
    ep.set_defaults(func=cmd_env_fix)

    # ---- Dispatch ----
    args = parser.parse_args()

    init_colors(args.no_color)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "service" and getattr(args, "service_command", None) is None:
        service_parser.print_help()
        return 0

    if args.command == "env" and getattr(args, "env_command", None) is None:
        env_parser.print_help()
        return 0

    if hasattr(args, "func"):
        return args.func(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
