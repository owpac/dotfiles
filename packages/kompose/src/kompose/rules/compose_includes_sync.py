"""Verify that service dirs and root compose includes stay in sync.

Direction A — per-service (`check`):
  Reports as an issue every service dir whose path is NOT listed in the root
  compose's `include:` block. Surfaced in the lint table under the rule's
  category column, attached to the offending service's row.

Direction B — host-wide (`notices`):
  Reports every `include:` entry whose target file does NOT exist on disk
  ("include orphan"). Surfaced in the post-table Notices section.

Both directions share a single `exclude:` list of service/dir names.

params:
  root: relative path to the root compose file (default: "compose.yml")
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from .._engine import FixApplied, Issue, LintContext


def _root_path(host_dir: Path, params: dict) -> Path:
    return host_dir / params.get("root", "compose.yml")


@lru_cache(maxsize=8)
def _read_includes(root_path: Path, mtime: float) -> list[tuple[str, str]]:
    """Return [(group_dir, include_path), ...] for each entry in `include:`.

    Cached on (path, mtime) so each lint run only reads the file once.
    """
    if not root_path.exists():
        return []
    try:
        data = yaml.safe_load(root_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return []

    out: list[tuple[str, str]] = []
    for entry in data.get("include") or []:
        path_str = entry if isinstance(entry, str) else (entry or {}).get("path", "")
        if not path_str:
            continue
        parts = Path(path_str).parts
        group = parts[-2] if len(parts) >= 2 else ""
        if group:
            out.append((group, path_str))
    return out


def _included_groups(root_path: Path) -> set[str]:
    if not root_path.exists():
        return set()
    mtime = root_path.stat().st_mtime
    return {g for g, _ in _read_includes(root_path, mtime)}


def check(ctx: LintContext, params: dict, exclude: set[str]) -> list[Issue]:
    """Direction A: this service must appear in the root compose's includes."""
    if ctx.service_name in exclude:
        return []
    host_dir = ctx.compose_path.parent.parent
    root_path = _root_path(host_dir, params)
    if not root_path.exists():
        return []
    if ctx.service_name in _included_groups(root_path):
        return []
    return [Issue(message=f"not in root compose include ({root_path.name})")]


def notices(host_dir: Path, services: list[Path], params: dict, exclude: set[str]) -> list[Issue]:
    """Direction B: every include path must point to an existing file."""
    root_path = _root_path(host_dir, params)
    if not root_path.exists():
        return []

    mtime = root_path.stat().st_mtime
    issues: list[Issue] = []
    for group, include_path in _read_includes(root_path, mtime):
        if group in exclude:
            continue
        full = host_dir / include_path
        if not full.exists():
            issues.append(Issue(
                message=f"include path missing on disk: {include_path}",
                location=str(root_path.name),
            ))
    return issues


def fix(ctx: LintContext, params: dict, exclude: set[str], *, force: bool = False, dry_run: bool = False) -> list[FixApplied]:
    """Auto-fix direction A: add the current service to the root compose's `include:`.

    Only fixes when the service is missing from the include list (= the same
    condition `check()` reports). Direction B (include without dir) is NOT
    auto-fixed — removing an include entry might mask a typo and is best left
    to the user.
    """
    if ctx.service_name in exclude:
        return []

    host_dir = ctx.compose_path.parent.parent
    root_path = _root_path(host_dir, params)
    if not root_path.exists():
        return []

    if ctx.service_name in _included_groups(root_path):
        return []  # nothing to fix

    # Determine the include path to add — by convention `<service>/compose.yml`
    relative_path = f"{ctx.service_name}/compose.yml"
    new_content = _add_include_entry(root_path.read_text(), relative_path)
    if new_content is None:
        return []  # couldn't locate the include block; refuse rather than corrupt

    if not dry_run:
        root_path.write_text(new_content)
        # Invalidate cache so subsequent calls in the same lint run see the update
        _read_includes.cache_clear()

    return [FixApplied(
        target=root_path.name,
        message=f"added `{relative_path}` to {root_path.name} include block",
    )]


def _add_include_entry(content: str, include_path: str) -> str | None:
    """Append `- path: <include_path>` to the `include:` block of a YAML doc.

    Returns the new content, or None if the include block couldn't be located.
    Preserves the existing indentation and entry style (short-form vs dict).
    """
    lines = content.split("\n")

    # Locate the top-level `include:` line.
    include_idx = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("include:") and len(line) - len(stripped) == 0:
            include_idx = i
            break
    if include_idx is None:
        return None

    # Locate the END of the include block (next top-level non-blank/non-comment line).
    end_idx = len(lines)
    for i in range(include_idx + 1, len(lines)):
        stripped = lines[i].lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if len(lines[i]) - len(stripped) == 0:
            end_idx = i
            break

    # Detect entry style (short-form vs dict) by inspecting the first existing entry.
    short_form = False
    entry_indent = "  "
    for i in range(include_idx + 1, end_idx):
        stripped = lines[i].lstrip()
        if not stripped.startswith("-"):
            continue
        entry_indent = " " * (len(lines[i]) - len(stripped))
        body = stripped[1:].lstrip()
        short_form = not body.startswith("path:")
        break

    if short_form:
        new_entry = f"{entry_indent}- {include_path}"
    else:
        new_entry = f"{entry_indent}- path: {include_path}"

    # Insert at the last position of the include block (just before end_idx).
    insert_at = end_idx
    # Trim trailing blanks INSIDE the block so the new entry isn't isolated.
    while insert_at - 1 > include_idx and not lines[insert_at - 1].strip():
        insert_at -= 1

    new_lines = lines[:insert_at] + [new_entry] + lines[insert_at:]
    return "\n".join(new_lines)
