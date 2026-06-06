"""CLI wiring for `kompose status` (and canonical `kompose service status`)."""

from __future__ import annotations

import argparse

from kompose.status import cmd_status

from . import _shared


def _add_status_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "service", nargs="?", metavar="<service>",
        help="Drill into a specific service: filter the table and tail its logs",
    ).complete = _shared.COMPLETE_SERVICE
    parser.add_argument("-s", "--stats", action="store_true", help="Show CPU and memory usage")
    parser.add_argument("-n", "--tail", default="30", metavar="N", help="Lines of log to show when drilling into a service (default: 30)")
    parser.add_argument("-f", "--follow", action="store_true", help="Live mode — with a service arg: follow logs after the tail; without: refresh the table every -i seconds")
    parser.add_argument("-i", "--interval", type=int, default=2, metavar="N", help="Refresh interval in seconds for live mode (default: 2)")
    parser.add_argument("--no-logs", action="store_true", help="Suppress the log tail when drilling into a service")


def register_top_level(subparsers) -> None:
    p = _shared.add_subparser(subparsers, "status", "Show services status (alias of: service status)", aliases=["st"])
    _add_status_args(p)
    p.set_defaults(func=cmd_status)


def register_canonical(service_subparsers) -> None:
    sp = _shared.add_subparser(service_subparsers, "status", "Show services status with IPs", aliases=["st"])
    _add_status_args(sp)
    sp.set_defaults(func=cmd_status)
