"""CLI wiring for compose lifecycle (up/down/restart/logs).

`register_top_level(subparsers)` adds the daily-ergonomics aliases under the
root parser. `register_canonical(service_subparsers)` mirrors them under the
canonical `service <verb>` noun-verb form (called from cli.service).
"""

from __future__ import annotations

import argparse

from kompose.compose import cmd_down, cmd_logs, cmd_restart, cmd_up

from . import _shared


def _add_lifecycle_args(parser: argparse.ArgumentParser) -> None:
    """Args shared by up/down/restart: <service> + <containers...>."""
    parser.add_argument(
        "service", nargs="?", metavar="<service>",
        help="Service (group dir) or docker compose service name",
    ).complete = _shared.COMPLETE_SERVICE
    parser.add_argument(
        "containers", nargs="*", metavar="<container>",
        help="Specific containers within the service",
    ).complete = _shared.COMPLETE_CONTAINER


def _add_logs_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "service", metavar="<service>", help="Service to view logs",
    ).complete = _shared.COMPLETE_SERVICE
    parser.add_argument(
        "containers", nargs="*", metavar="<container>",
        help="Specific containers within the service",
    ).complete = _shared.COMPLETE_CONTAINER
    parser.add_argument("-f", "--follow", action="store_true", default=True, help="Follow log output (default)")
    parser.add_argument("--no-follow", action="store_false", dest="follow", help="Don't follow log output")
    parser.add_argument("-n", "--tail", default="100", metavar="N", help="Number of lines to show (default: 100)")


def register_top_level(subparsers) -> None:
    p = _shared.add_subparser(subparsers, "up", "Start services (alias of: service up)")
    _add_lifecycle_args(p)
    p.set_defaults(func=cmd_up)

    p = _shared.add_subparser(subparsers, "down", "Stop services (alias of: service down)")
    _add_lifecycle_args(p)
    p.set_defaults(func=cmd_down)

    p = _shared.add_subparser(subparsers, "restart", "Restart services (alias of: service restart)", aliases=["r"])
    _add_lifecycle_args(p)
    p.set_defaults(func=cmd_restart)

    p = _shared.add_subparser(subparsers, "logs", "View service logs (alias of: service logs)", aliases=["l"])
    _add_logs_args(p)
    p.set_defaults(func=cmd_logs)


def register_canonical(service_subparsers) -> None:
    sp = _shared.add_subparser(service_subparsers, "up", "Start services")
    _add_lifecycle_args(sp)
    sp.set_defaults(func=cmd_up)

    sp = _shared.add_subparser(service_subparsers, "down", "Stop services")
    _add_lifecycle_args(sp)
    sp.set_defaults(func=cmd_down)

    sp = _shared.add_subparser(service_subparsers, "restart", "Restart services", aliases=["r"])
    _add_lifecycle_args(sp)
    sp.set_defaults(func=cmd_restart)

    sp = _shared.add_subparser(service_subparsers, "logs", "View service logs", aliases=["l"])
    _add_logs_args(sp)
    sp.set_defaults(func=cmd_logs)
