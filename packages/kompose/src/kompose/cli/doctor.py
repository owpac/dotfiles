"""CLI wiring for `kompose doctor` — validates .kompose/ configuration."""

from __future__ import annotations

import argparse

from kompose.doctor import cmd_doctor

from . import _shared


def _add_doctor_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--rules", action="store_true", help="Only check .kompose/rules.yaml")
    parser.add_argument("--commands", action="store_true", help="Only check .kompose/commands.yaml")
    parser.add_argument("--config", action="store_true", help="Only check the XDG user config (~/.config/kompose/config.yaml)")


def register_top_level(subparsers) -> None:
    p = _shared.add_subparser(
        subparsers, "doctor",
        "Validate kompose's own config in .kompose/ (rules.yaml, commands.yaml)",
    )
    _add_doctor_args(p)
    p.set_defaults(func=cmd_doctor)
