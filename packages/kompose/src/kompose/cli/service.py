"""CLI wiring for the canonical noun-verb form: `kompose service <verb>`.

Adds the `service` (and `svc` alias) parent subparser, then re-uses each
lifecycle command's `register_canonical()` to attach the same verbs that
exist at the top level.
"""

from __future__ import annotations

from . import _shared, compose, status


def register(subparsers):
    parent = _shared.add_subparser(
        subparsers, "service",
        "Service lifecycle (canonical noun-verb form)",
        aliases=["svc"],
    )
    sub = parent.add_subparsers(dest="service_command", metavar="<verb>")
    compose.register_canonical(sub)
    status.register_canonical(sub)
    return parent
