"""CLI wiring for `kompose upgrade` (watchtower HTTP trigger)."""

from __future__ import annotations

import argparse

from kompose.upgrade import cmd_upgrade

from . import _shared


def _add_upgrade_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "service", nargs="?", metavar="<service>",
        help="Service group to upgrade (default: all containers)",
    ).complete = _shared.COMPLETE_SERVICE
    parser.add_argument("-f", "--force", action="store_true", help="Skip confirmation on the global form")
    parser.add_argument("--logs", action="store_true", help="Render the latest watchtower session (no trigger)")


def register_top_level(subparsers) -> None:
    p = _shared.add_subparser(subparsers, "upgrade", "Trigger image updates via watchtower's HTTP API")
    _add_upgrade_args(p)
    p.set_defaults(func=cmd_upgrade)
