"""Tests for config module."""

import unittest
from pathlib import Path

from kompose.config import (
    DEFAULT_HOST,
    WORKSPACE_DIR,
    get_base_dir,
    get_host_dir,
)


class TestPaths(unittest.TestCase):
    def test_default_host_dir(self):
        self.assertEqual(get_host_dir(), WORKSPACE_DIR / DEFAULT_HOST)

    def test_explicit_host_dir(self):
        self.assertEqual(get_host_dir("other"), WORKSPACE_DIR / "other")

    def test_base_dir(self):
        self.assertEqual(get_base_dir(), WORKSPACE_DIR / "base")


if __name__ == "__main__":
    unittest.main()
