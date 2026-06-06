"""CLI wiring for `kompose check`."""

from __future__ import annotations

import argparse

from kompose.lint import cmd_check

from . import _shared


def _add_check_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "service", nargs="?", metavar="<service>",
        help="Service to check (default: all)",
    ).complete = _shared.COMPLETE_SERVICE


def register_top_level(subparsers) -> None:
    p = _shared.add_subparser(subparsers, "check", "Lint compose files and env drift")
    _add_check_args(p)
    p.set_defaults(func=cmd_check)
