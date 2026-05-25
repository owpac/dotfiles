"""Public routers must use wan middleware, private routers must use lan.

Reads from globals (with sensible defaults):
  public_domain      (default: 'owpac.com')
  private_domain     (default: 'owpac.net')
  public_middleware  (default: 'wan@file')
  private_middleware (default: 'lan@file')

exclude: router names (string IDs) to ignore.
"""

from __future__ import annotations

import re

from .._engine import Issue, LintContext

_RULE_PATTERN = r"traefik\.http\.routers\.([a-z0-9-]+)\.rule[^:]*:[^`]*`([^`]+)`"
_MIDDLEWARE_PATTERN = r"traefik\.http\.routers\.([a-z0-9-]+)\.middlewares[^:]*:[^\n]*"
_ALWAYS_IGNORE = {"wildcard-certs"}


def check(ctx: LintContext, params: dict, exclude: set[str]) -> list[Issue]:
    public_domain = ctx.globals.get("public_domain", "owpac.com")
    private_domain = ctx.globals.get("private_domain", "owpac.net")
    public_mw = ctx.globals.get("public_middleware", "wan@file")
    private_mw = ctx.globals.get("private_middleware", "lan@file")

    rules = dict(re.findall(_RULE_PATTERN, ctx.content))
    issues: list[Issue] = []

    for match in re.finditer(_MIDDLEWARE_PATTERN, ctx.content):
        router = match.group(1)
        middleware_line = match.group(0)

        if router in _ALWAYS_IGNORE or router in exclude:
            continue

        rule = rules.get(router, "")
        is_public = public_domain in rule
        is_private = private_domain in rule

        if is_public and public_mw not in middleware_line:
            issues.append(Issue(message=f"{router} (public needs {public_mw})"))
        elif is_private and private_mw not in middleware_line:
            issues.append(Issue(message=f"{router} (private needs {private_mw})"))

    return issues
