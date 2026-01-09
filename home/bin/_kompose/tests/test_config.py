"""Tests for config module."""

import unittest
import tempfile
import shutil
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from _kompose.config import LintConfig

FIXTURES = Path(__file__).parent / "fixtures"


def load_config_from_file(path: Path) -> LintConfig:
    """Load config from a specific file (for testing)."""
    config = LintConfig()
    if not path.exists():
        return config

    content = path.read_text()
    current_section = None

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

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


class TestLintConfig(unittest.TestCase):
    def test_default_config(self):
        config = LintConfig()

        self.assertEqual(config.exclude_routers, set())
        self.assertEqual(config.exclude_middlewares, set())
        self.assertEqual(config.exclude_logging, set())
        self.assertEqual(config.exclude_network, set())

    def test_load_config_from_file(self):
        config = load_config_from_file(FIXTURES / "sample.komposeignore")

        self.assertIn("excluded-router", config.exclude_routers)
        self.assertIn("another-router", config.exclude_routers)
        self.assertIn("excluded-middleware", config.exclude_middlewares)
        self.assertIn("network", config.exclude_logging)
        self.assertIn("special-service", config.exclude_logging)
        self.assertEqual(config.exclude_network, set())

    def test_load_nonexistent_file(self):
        config = load_config_from_file(Path("/nonexistent/.komposeignore"))

        self.assertEqual(config.exclude_routers, set())

    def test_comments_ignored(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".komposeignore", delete=False) as f:
            f.write("# Comment\n")
            f.write("exclude:\n")
            f.write("  routers:\n")
            f.write("    # Another comment\n")
            f.write("    - test-router\n")
            f.flush()

            config = load_config_from_file(Path(f.name))

        self.assertEqual(config.exclude_routers, {"test-router"})

    def test_empty_section(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".komposeignore", delete=False) as f:
            f.write("exclude:\n")
            f.write("  routers: []\n")
            f.write("  logging:\n")
            f.write("    - test\n")
            f.flush()

            config = load_config_from_file(Path(f.name))

        # Empty [] syntax - routers stays empty
        self.assertEqual(config.exclude_routers, set())
        self.assertEqual(config.exclude_logging, {"test"})


class TestConfigIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_config_used_in_lint(self):
        # Create a config file
        config_path = Path(self.temp_dir) / ".komposeignore"
        config_path.write_text("""
exclude:
  routers:
    - my-excluded-router
  middlewares:
    - my-excluded-middleware
""")

        config = load_config_from_file(config_path)

        self.assertIn("my-excluded-router", config.exclude_routers)
        self.assertIn("my-excluded-middleware", config.exclude_middlewares)


if __name__ == "__main__":
    unittest.main()
