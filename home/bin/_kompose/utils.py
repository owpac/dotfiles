"""Shared utilities for colors, tables, and prompts."""

import re
import sys


class Colors:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    GRAY = "\033[90m"
    CYAN = "\033[96m"
    RESET = "\033[0m"
    BOLD = "\033[1m"

    @classmethod
    def disable(cls):
        for attr in ["RED", "GREEN", "YELLOW", "BLUE", "GRAY", "CYAN", "RESET", "BOLD"]:
            setattr(cls, attr, "")


class Table:
    def __init__(self, headers: list[str]):
        self.headers = headers
        self.rows: list[list[str]] = []
        self.widths = [len(h) for h in headers]

    def add_row(self, row: list[str]) -> None:
        self.rows.append(row)
        for i, cell in enumerate(row):
            clean = re.sub(r"\033\[[0-9;]*m", "", cell)
            self.widths[i] = max(self.widths[i], len(clean))

    def render(self) -> str:
        if not self.rows:
            return ""

        def pad(text: str, width: int) -> str:
            clean = re.sub(r"\033\[[0-9;]*m", "", text)
            return text + " " * (width - len(clean))

        lines = []
        header_line = "  ".join(pad(h, self.widths[i]) for i, h in enumerate(self.headers))
        lines.append(f"{Colors.BOLD}{header_line}{Colors.RESET}")
        lines.append(f"{Colors.GRAY}{chr(9472) * (sum(self.widths) + 2 * (len(self.headers) - 1))}{Colors.RESET}")
        for row in self.rows:
            lines.append("  ".join(pad(cell, self.widths[i]) for i, cell in enumerate(row)))
        return "\n".join(lines)


def confirm(prompt: str) -> bool:
    """Ask for user confirmation."""
    try:
        response = input(f"{prompt} [y/N] ").strip().lower()
        return response in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def init_colors(no_color: bool = False) -> None:
    """Initialize color settings based on flags and TTY."""
    if no_color or not sys.stdout.isatty():
        Colors.disable()
