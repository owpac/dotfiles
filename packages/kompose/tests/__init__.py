"""Tests for kompose CLI.

Adds the package `src/` to sys.path so tests can run without `pip install -e .`.
When the package is installed (editable or not), this is a no-op.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
