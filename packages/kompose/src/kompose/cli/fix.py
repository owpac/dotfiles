"""CLI wiring for `kompose fix`."""

from __future__ import annotations

import argparse

from kompose.fix import cmd_fix

from . import _shared


def _add_fix_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "service", nargs="?", metavar="<service>",
        help="Service to fix (default: all)",
    ).complete = _shared.COMPLETE_SERVICE
    parser.add_argument("-f", "--force", action="store_true", help="Skip confirmation, apply defaults")
    parser.add_argument("--dry-run", action="store_true", help="Preview what would change without applying")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--auto", action="store_true", help="Only run compose-level auto-fixes (skip the interactive env sync)")
    scope.add_argument("--env", action="store_true", help="Only run the interactive env sync (skip compose-level rule fixes)")


def register_top_level(subparsers) -> None:
    p = _shared.add_subparser(
        subparsers, "fix",
        "Apply fixes (compose auto-fixes + interactive env sync). Scope: --auto or --env.",
    )
    _add_fix_args(p)
    p.set_defaults(func=cmd_fix)
