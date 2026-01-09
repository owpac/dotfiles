"""Configuration and settings."""

import re
from dataclasses import dataclass, field
from pathlib import Path

WORKSPACE_DIR = Path("/mnt/home/thomas/workspace/homelab")
DEFAULT_HOST = "nas"


@dataclass
class LintConfig:
    exclude_routers: set[str] = field(default_factory=set)
    exclude_middlewares: set[str] = field(default_factory=set)
    exclude_logging: set[str] = field(default_factory=set)
    exclude_network: set[str] = field(default_factory=set)


def get_host_dir(host: str | None = None) -> Path:
    """Get the directory for a host."""
    return WORKSPACE_DIR / (host or DEFAULT_HOST)


def get_base_dir() -> Path:
    """Get the base directory for shared compose files."""
    return WORKSPACE_DIR / "base"


def get_ignore_file(host: str | None = None) -> Path:
    """Get the .komposeignore file path for a host."""
    return get_host_dir(host) / ".komposeignore"


def load_config(host: str | None = None) -> LintConfig:
    """Load configuration from .komposeignore."""
    config = LintConfig()
    ignore_file = get_ignore_file(host)

    # Also check for legacy .homelabignore
    if not ignore_file.exists():
        ignore_file = get_host_dir(host) / ".homelabignore"

    if not ignore_file.exists():
        return config

    content = ignore_file.read_text()
    current_section = None

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Check for section headers
        if stripped == "exclude:":
            continue
        if stripped.endswith(":") and not stripped.startswith("-"):
            section = stripped.rstrip(":")
            if section == "routers":
                current_section = "routers"
            elif section == "middlewares":
                current_section = "middlewares"
            elif section == "logging":
                current_section = "logging"
            elif section == "network":
                current_section = "network"
            else:
                current_section = None
            continue

        # Parse list items
        if stripped.startswith("- ") and current_section:
            value = stripped[2:].strip()
            if current_section == "routers":
                config.exclude_routers.add(value)
            elif current_section == "middlewares":
                config.exclude_middlewares.add(value)
            elif current_section == "logging":
                config.exclude_logging.add(value)
            elif current_section == "network":
                config.exclude_network.add(value)

    return config


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
