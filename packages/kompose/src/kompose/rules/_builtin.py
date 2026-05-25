"""Built-in rule types invoked from YAML `type:` field."""

from __future__ import annotations

from .._engine import Issue, LintContext


def substring_required(ctx: LintContext, params: dict, exclude: set[str]) -> list[Issue]:
    """Fail if any of the configured substrings is missing from the compose file.

    params:
      required: [str, ...]
    exclude: list of service names (= service directory names) to skip.
    """
    if ctx.service_name in exclude:
        return []
    required = params.get("required") or []
    if isinstance(required, str):
        required = [required]
    missing = [s for s in required if s not in ctx.content]
    return [Issue(message=f"missing '{s}'") for s in missing]


def substring_forbidden(ctx: LintContext, params: dict, exclude: set[str]) -> list[Issue]:
    """Fail if any of the configured substrings is present in the compose file.

    params:
      forbidden: [str, ...]
    exclude: list of service names to skip.
    """
    if ctx.service_name in exclude:
        return []
    forbidden = params.get("forbidden") or []
    if isinstance(forbidden, str):
        forbidden = [forbidden]
    return [Issue(message=f"forbidden '{s}'") for s in forbidden if s in ctx.content]


def _extract_service_props(content: str) -> dict[str, list[tuple[str, int]]]:
    services: dict[str, list[tuple[str, int]]] = {}
    lines = content.split("\n")
    current_service = None
    in_services_block = False
    service_indent = None
    prop_indent = None

    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if stripped.startswith("services:"):
            in_services_block = True
            continue
        if not in_services_block:
            continue
        if indent == 0 and stripped and not stripped.startswith("#"):
            in_services_block = False
            continue
        if not stripped or stripped.startswith("#"):
            continue
        if service_indent is None and indent > 0 and stripped.endswith(":") and not stripped.startswith("-"):
            service_indent = indent
        if indent == service_indent and stripped.endswith(":") and not stripped.startswith("-"):
            current_service = stripped.rstrip(":").strip()
            services[current_service] = []
            prop_indent = None
            continue
        if current_service and service_indent is not None and indent > service_indent:
            if prop_indent is None:
                prop_indent = indent
            if indent == prop_indent and ":" in stripped and not stripped.startswith("-"):
                prop_name = stripped.split(":")[0].strip()
                services[current_service].append((prop_name, i))

    return services


def _order_issues_for_container(container: str, props: list[tuple[str, int]], expected_order: list[str]) -> list[Issue]:
    known_props = [(name, line) for name, line in props if name in expected_order]
    if not known_props:
        return []

    prop_names_present = [p[0] for p in props]
    expected_present = [p for p in expected_order if p in prop_names_present]
    actual = [name for name, _ in known_props]
    if actual == expected_present:
        return []

    issues: list[Issue] = []
    seen_moves: set[str] = set()
    for i, (prop, line) in enumerate(known_props):
        expected_idx = expected_present.index(prop)
        for j in range(i):
            other_prop = known_props[j][0]
            other_expected_idx = expected_present.index(other_prop)
            if other_expected_idx > expected_idx and prop not in seen_moves:
                issues.append(Issue(
                    message=f"{container}: move `{prop}` before `{other_prop}`",
                    location=f"{container}:{line}",
                    fix=f"move `{prop}` before `{other_prop}`",
                ))
                seen_moves.add(prop)
                break
    return issues


def property_order(ctx: LintContext, params: dict, exclude: set[str]) -> list[Issue]:
    """Verify each service's properties follow a defined order.

    params:
      order: [container_name, depends_on, env_file, ...]
    exclude: list of container names to skip (note: matches the *container* key
             inside `services:`, not the service directory).
    """
    expected_order = params.get("order") or []
    if not expected_order:
        return []

    issues: list[Issue] = []
    for container, props in _extract_service_props(ctx.content).items():
        if container in exclude:
            continue
        issues.extend(_order_issues_for_container(container, props, expected_order))
    return issues
