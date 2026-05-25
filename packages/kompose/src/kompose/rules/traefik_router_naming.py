"""Public Traefik routers must use a -private/-public suffix.

Reads from globals (with sensible defaults):
  public_domain   (default: 'owpac.com')
  private_domain  (default: 'owpac.net')

params:
  required_suffixes: [str, ...]  (default: ['-private', '-public'])

exclude: router names (string IDs) to ignore.
"""

from __future__ import annotations

import re

from .._engine import Issue, LintContext

_ROUTER_PATTERN = r"traefik\.http\.routers\.([a-z0-9-]+)\."
_ALWAYS_IGNORE = {"wildcard-certs"}


def check(ctx: LintContext, params: dict, exclude: set[str]) -> list[Issue]:
    public_domain = ctx.globals.get("public_domain", "owpac.com")
    suffixes = tuple(params.get("required_suffixes") or ["-private", "-public"])
    private_suffixes = tuple(s for s in suffixes if s != "-public")

    has_public = public_domain in ctx.content
    routers = sorted(set(re.findall(_ROUTER_PATTERN, ctx.content)))

    issues: list[Issue] = []
    for router in routers:
        if router in _ALWAYS_IGNORE or router in exclude:
            continue
        has_required_suffix = any(router.endswith(s) for s in suffixes)
        if has_public:
            if not has_required_suffix:
                missing = "/".join(suffixes)
                issues.append(Issue(message=f"{router} (missing {missing})"))
        else:
            if router.endswith("-public"):
                hint = private_suffixes[0] if private_suffixes else "-private"
                issues.append(Issue(message=f"{router} (use {hint} for private domain)"))
    return issues
