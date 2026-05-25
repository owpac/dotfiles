"""Each service must join the proxy network OR use network_mode.

Reads from globals (with sensible defaults):
  proxy_network         (default: 'reverse-proxy')
  network_mode_keyword  (default: 'network_mode')

exclude: service names (= service directory names) to skip.
"""

from __future__ import annotations

from .._engine import Issue, LintContext


def check(ctx: LintContext, params: dict, exclude: set[str]) -> list[Issue]:
    if ctx.service_name in exclude:
        return []

    proxy_network = ctx.globals.get("proxy_network", "reverse-proxy")
    network_mode_keyword = ctx.globals.get("network_mode_keyword", "network_mode")

    if proxy_network in ctx.content or network_mode_keyword in ctx.content:
        return []
    return [Issue(message=f"missing network: {proxy_network}")]
