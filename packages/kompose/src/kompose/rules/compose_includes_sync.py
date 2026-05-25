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

from .._engine import Issue, LintContext


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
