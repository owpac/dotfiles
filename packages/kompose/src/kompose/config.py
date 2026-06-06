"""Configuration and paths.

Resolution chain for `WORKSPACE_DIR` and `DEFAULT_HOST` (highest priority first):

  1. `--host <name>` CLI flag           — overrides `DEFAULT_HOST` for that
                                          invocation only; no equivalent CLI
                                          flag for the workspace today.
  2. Environment variables              — `KOMPOSE_WORKSPACE`, `KOMPOSE_HOST`.
                                          One-shot overrides (and the same
                                          vars the zsh completion preamble
                                          reads).
  3. XDG config file                    — `$XDG_CONFIG_HOME/kompose/config.yaml`
                                          (default `~/.config/kompose/config.yaml`).
                                          Two keys: `workspace:`, `host:`.
  4. Hardcoded fallback                 — the homelab/NAS defaults this CLI
                                          was originally built for.

Resolved once at import time. Tests patch `WORKSPACE_DIR` / `DEFAULT_HOST`
directly (or call `_resolve()` after manipulating env / `XDG_CONFIG_HOME`).
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml


_HARDCODED_WORKSPACE = "/mnt/home/thomas/workspace/homelab"
_HARDCODED_HOST = "nas"


def _xdg_config_home() -> Path:
    """Honour `$XDG_CONFIG_HOME`; default to `~/.config` per the XDG spec."""
    raw = os.environ.get("XDG_CONFIG_HOME")
    return Path(raw) if raw else Path.home() / ".config"


def _config_file_path() -> Path:
    return _xdg_config_home() / "kompose" / "config.yaml"


def _load_file_config(path: Path) -> dict:
    """Read the optional XDG config file. Silently skip on missing / malformed
    files — the hardcoded fallback keeps the CLI usable.
    """
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _resolve() -> tuple[Path, str]:
    """Apply the precedence chain and return (workspace_dir, default_host)."""
    file_config = _load_file_config(_config_file_path())
    workspace = (
        os.environ.get("KOMPOSE_WORKSPACE")
        or file_config.get("workspace")
        or _HARDCODED_WORKSPACE
    )
    host = (
        os.environ.get("KOMPOSE_HOST")
        or file_config.get("host")
        or _HARDCODED_HOST
    )
    return Path(workspace), host


WORKSPACE_DIR, DEFAULT_HOST = _resolve()


def get_host_dir(host: str | None = None) -> Path:
    """Get the directory for a host."""
    return WORKSPACE_DIR / (host or DEFAULT_HOST)


def get_base_dir() -> Path:
    """Get the base directory for shared compose files."""
    return WORKSPACE_DIR / "base"


def get_services(host: str | None = None) -> list[Path]:
    """Get all service directories for a host."""
    host_dir = get_host_dir(host)
    services = []
    if not host_dir.exists():
        return services
    for item in host_dir.iterdir():
        if item.is_dir() and (item / "compose.yml").exists():
            services.append(item)
    return sorted(services)
