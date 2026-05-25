"""Verify that each service's .env and .env.example stay in sync.

Reuses `check_service_env` from kompose.env so the rule and the standalone
`kompose env check` command share the same logic.

For each affected service, one Issue per variable in drift, plus one Issue
if there is a structure drift (comments / blank lines / ordering / trailing
newline). Missing `.env` files are reported as N issues (one per variable
declared in `.env.example`).

Services without `.env.example` are skipped silently (they have no env
config to compare against).

exclude: service names to skip entirely.
"""

from __future__ import annotations

from .._engine import Issue, LintContext
from ..env import (
    ENV_STATUS_DRIFT,
    ENV_STATUS_MISSING,
    ENV_STATUS_NO_EXAMPLE,
    check_service_env,
)


def check(ctx: LintContext, params: dict, exclude: set[str]) -> list[Issue]:
    if ctx.service_name in exclude:
        return []

    service_dir = ctx.compose_path.parent
    result = check_service_env(service_dir)

    if result.status == ENV_STATUS_NO_EXAMPLE:
        return []

    issues: list[Issue] = []

    if result.status == ENV_STATUS_MISSING:
        for var in result.only_in_example:
            issues.append(Issue(
                message=f"missing var `{var}` (.env file not found)",
                location=".env",
            ))
        return issues

    # ENV_STATUS_DRIFT
    for var in result.only_in_env:
        issues.append(Issue(
            message=f"extra var `{var}` in .env (not in .env.example)",
            location=".env",
        ))
    for var in result.only_in_example:
        issues.append(Issue(
            message=f"missing var `{var}` in .env",
            location=".env.example",
        ))
    if result.structure_drift:
        issues.append(Issue(
            message="structure drift (order / comments / blank lines)",
            location=".env.example",
            fix="run `kompose env sync`",
        ))
    return issues
