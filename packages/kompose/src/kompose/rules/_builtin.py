"""Built-in rule types invoked from YAML `type:` field."""

from __future__ import annotations

from .._engine import FixApplied, Issue, LintContext


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
      warn_on_unknown: bool (default True). When True, also reports each
        property that is NOT in the `order` list. Lets the user decide whether
        to add the key to `order:` (canonicalize) or accept it as a
        free-position key (set `warn_on_unknown: false` to silence).

    exclude: list of container names to skip (note: matches the *container* key
             inside `services:`, not the service directory).
    """
    expected_order = params.get("order") or []
    warn_on_unknown = params.get("warn_on_unknown", True)
    if not expected_order:
        return []

    issues: list[Issue] = []
    for container, props in _extract_service_props(ctx.content).items():
        if container in exclude:
            continue
        issues.extend(_order_issues_for_container(container, props, expected_order))
        if warn_on_unknown:
            for prop_name, line in props:
                if prop_name not in expected_order:
                    issues.append(Issue(
                        message=f"{container}: unknown property `{prop_name}` (not in rule's `order` list)",
                        location=f"{container}:{line}",
                    ))
    return issues


# ---------------------------------------------------------------------------
# property_order — auto-fix via text manipulation (no ruamel dep)
# ---------------------------------------------------------------------------


def _find_top_level_key(lines: list[str], key: str) -> int | None:
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(f"{key}:") and len(line) - len(stripped) == 0:
            return i
    return None


def _find_next_top_level(lines: list[str], start: int) -> int:
    for i in range(start, len(lines)):
        stripped = lines[i].lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if len(lines[i]) - len(stripped) == 0:
            return i
    return len(lines)


def _find_first_child_indent(lines: list[str], start: int, end: int) -> int | None:
    for i in range(start, end):
        stripped = lines[i].lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(lines[i]) - len(stripped)
        if indent > 0 and stripped.endswith(":") and not stripped.startswith("-"):
            return indent
    return None


def _reorder_service_block(body: list[str], expected_order: list[str]) -> tuple[list[str], bool]:
    """Reorder property blocks inside a single service body. Returns (new_body, changed)."""
    if not body:
        return body, False

    prop_indent: int | None = None
    for line in body:
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#"):
            indent = len(line) - len(stripped)
            if ":" in stripped and not stripped.startswith("-"):
                prop_indent = indent
                break
    if prop_indent is None:
        return body, False

    blocks: list[tuple[str | None, list[str]]] = []
    buffered: list[str] = []
    current_prop: str | None = None
    current_lines: list[str] = []

    for line in body:
        stripped = line.lstrip()
        indent = len(line) - len(stripped) if stripped else 0

        if not stripped or stripped.startswith("#"):
            # Comment or blank: attach to NEXT property (so reorder moves it correctly).
            # Exception: if it sits inside a value block (indent > prop_indent), keep it
            # with the current property.
            if current_prop is None:
                buffered.append(line)
            elif stripped and indent > prop_indent:
                current_lines.append(line)
            else:
                buffered.append(line)
            continue

        is_property = (
            indent == prop_indent
            and ":" in stripped
            and not stripped.startswith("-")
        )

        if is_property:
            if current_prop is not None:
                blocks.append((current_prop, current_lines))
            current_prop = stripped.split(":")[0].strip()
            current_lines = buffered + [line]
            buffered = []
        else:
            current_lines.extend(buffered)
            buffered = []
            current_lines.append(line)

    if current_prop is not None:
        blocks.append((current_prop, current_lines))
    trailing = buffered  # blanks/comments after the last property stay at the end

    # Only reorder KNOWN properties — leave unknown ones (e.g. `build:`,
    # `secrets:`) in their original positions. This matches the check's
    # definition of "wrong order" (`_order_issues_for_container` only compares
    # the relative order of known props), so `kompose fix` never wants to
    # change a file that `kompose check` says is fine.
    known_indices = [i for i, (p, _) in enumerate(blocks) if p in expected_order]
    known_blocks_in_order = [blocks[i] for i in known_indices]
    expected_blocks = sorted(
        known_blocks_in_order,
        key=lambda b: expected_order.index(b[0]),
    )

    changed = [b[0] for b in known_blocks_in_order] != [b[0] for b in expected_blocks]

    if changed:
        new_blocks = list(blocks)
        for slot_idx, sorted_block in zip(known_indices, expected_blocks):
            new_blocks[slot_idx] = sorted_block
    else:
        new_blocks = blocks

    new_body: list[str] = []
    for _, lines_ in new_blocks:
        new_body.extend(lines_)
    new_body.extend(trailing)
    return new_body, changed


def _reorder_compose_keys(content: str, expected_order: list[str], exclude: set[str]) -> tuple[str, list[str]]:
    """Reorder property keys within each service of a compose file.

    Returns (new_content, list of container names whose body changed).
    """
    lines = content.split("\n")

    services_idx = _find_top_level_key(lines, "services")
    if services_idx is None:
        return content, []

    services_end = _find_next_top_level(lines, services_idx + 1)
    body_start, body_end = services_idx + 1, services_end

    service_indent = _find_first_child_indent(lines, body_start, body_end)
    if service_indent is None:
        return content, []

    new_body: list[str] = []
    changed: list[str] = []
    i = body_start
    while i < body_end:
        line = lines[i]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        is_service_header = (
            stripped and not stripped.startswith("#")
            and indent == service_indent
            and stripped.endswith(":")
            and not stripped.startswith("-")
        )

        if is_service_header:
            container = stripped.rstrip(":").strip()
            new_body.append(line)
            svc_start = i + 1
            svc_end = svc_start
            for j in range(svc_start, body_end):
                line_j = lines[j]
                stripped_j = line_j.lstrip()
                indent_j = len(line_j) - len(stripped_j)
                if (stripped_j and not stripped_j.startswith("#")
                        and indent_j == service_indent
                        and stripped_j.endswith(":")
                        and not stripped_j.startswith("-")):
                    break
                svc_end = j + 1

            svc_body = lines[svc_start:svc_end]
            if container in exclude:
                new_body.extend(svc_body)
            else:
                reordered, was_changed = _reorder_service_block(svc_body, expected_order)
                if was_changed:
                    changed.append(container)
                new_body.extend(reordered)
            i = svc_end
        else:
            new_body.append(line)
            i += 1

    new_lines = lines[:body_start] + new_body + lines[body_end:]
    return "\n".join(new_lines), changed


def property_order_fix(ctx: LintContext, params: dict, exclude: set[str], *, force: bool = False, dry_run: bool = False) -> list[FixApplied]:
    """Auto-fix the property_order rule: reorder service keys to match `expected_order`.

    Preserves comments and exact formatting of value blocks. Comments between
    two properties are treated as 'leading for the next property' and move with it.
    """
    expected_order = params.get("order") or []
    if not expected_order:
        return []

    new_content, changed = _reorder_compose_keys(ctx.content, expected_order, exclude)
    if not changed:
        return []

    if not dry_run:
        ctx.compose_path.write_text(new_content)

    return [FixApplied(
        target=f"{ctx.service_name}/compose.yml",
        message=f"reordered properties in {', '.join(changed)}",
    )]


