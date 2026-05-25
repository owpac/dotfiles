"""Configuration and paths."""

from pathlib import Path

WORKSPACE_DIR = Path("/mnt/home/thomas/workspace/homelab")
DEFAULT_HOST = "nas"


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
