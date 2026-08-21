"""Each service must be attached to exactly the networks declared for it.

Replaces the older single-network check, which could only assert one literal
name and so had nothing to say once the compose project grew several
Traefik-facing zones. The mapping below is the authoritative record of which
service belongs to which zone, so moving a service without updating it is an
error rather than a silent 502.

params:
  networks:  {network_name: [service, ...]}  membership, one entry per network

Declared network-first so the rule file reads like the zone table it mirrors: a
network on the left, the services it holds on the right. A service legitimately
on several networks simply appears in each of them.

Coverage is not optional: a service listed in no network at all is an error,
since a partial map is exactly how a newly added service slips in unchecked.
Use `exclude:` for the one legitimate case, a service you deliberately leave
unconstrained.

A service declaring network_mode manages its own networking and is skipped.

exclude: service names (compose service keys) to skip entirely.
"""

from __future__ import annotations

from .._engine import Issue, LintContext


def _declared_networks(service: dict) -> set[str]:
    """Read a service's networks, which compose accepts as a list or a mapping."""
    networks = service.get("networks")
    if not networks:
        return set()
    if isinstance(networks, (dict, list)):
        return {n for n in networks if isinstance(n, str)}
    return set()


def _invert(zones: dict) -> dict[str, set[str]]:
    """Turn {network: [service, ...]} into {service: {network, ...}}."""
    by_service: dict[str, set[str]] = {}
    for network, members in (zones or {}).items():
        for service in members or []:
            by_service.setdefault(service, set()).add(network)
    return by_service


def check(ctx: LintContext, params: dict, exclude: set[str]) -> list[Issue]:
    expected_by_service = _invert(params.get("networks"))
    network_mode_keyword = ctx.globals.get("network_mode_keyword", "network_mode")

    services = (ctx.parsed or {}).get("services") or {}
    if not isinstance(services, dict):
        return []

    issues: list[Issue] = []
    for name, service in sorted(services.items()):
        if name in exclude or not isinstance(service, dict):
            continue
        if network_mode_keyword in service:
            continue

        if name not in expected_by_service:
            issues.append(Issue(message=f"{name}: listed in no network"))
            continue

        expected = expected_by_service[name]
        actual = _declared_networks(service)

        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if missing:
            issues.append(Issue(message=f"{name}: missing {', '.join(missing)}"))
        if unexpected:
            issues.append(Issue(message=f"{name}: unexpected {', '.join(unexpected)}"))

    return issues
