"""CLI plumbing for kompose subcommands.

Each module here owns the argparse + zsh-completion plumbing for one
top-level subcommand (or family of subcommands). Per-command exec logic
stays in the sibling top-level modules (`kompose.commands`,
`kompose.compose`, `kompose.status`, …).

Conventions:
- `register_top_level(subparsers)` — adds top-level aliases (e.g. `up`,
  `status`, `run`). Implemented by every cli module.
- `register_canonical(service_subparsers)` — adds the `service <verb>`
  variant. Implemented only by modules that have a canonical form
  (compose, status).
- `ZSH_PREAMBLE` — optional. If present, it's concatenated into the shtab
  preamble so the module's completion helpers are available in the
  generated script.
"""

from . import _shared, check, compose, fix, run, service, status, upgrade

__all__ = [
    "_shared",
    "check",
    "compose",
    "fix",
    "run",
    "service",
    "status",
    "upgrade",
]
