"""Tests for env module."""

import unittest
import tempfile
import shutil
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from _kompose.env import (
    parse_env_file,
    read_env_lines,
    find_insert_position,
    add_vars_to_env_file,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestParseEnvFile(unittest.TestCase):
    def test_parse_valid_env(self):
        env = parse_env_file(FIXTURES / "sample.env")

        self.assertEqual(env["PUID"], "1000")
        self.assertEqual(env["PGID"], "1000")
        self.assertEqual(env["TZ"], "Europe/Paris")
        self.assertEqual(env["DB_HOST"], "localhost")
        self.assertEqual(env["DB_USER"], "admin")
        self.assertEqual(env["DB_PASS"], "secret")

    def test_parse_env_example(self):
        env = parse_env_file(FIXTURES / "sample.env.example")

        self.assertEqual(env["PUID"], "''")
        self.assertEqual(env["API_KEY"], "''")

    def test_parse_nonexistent_file(self):
        env = parse_env_file(Path("/nonexistent/path/.env"))

        self.assertEqual(env, {})

    def test_parse_ignores_comments(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("# This is a comment\n")
            f.write("KEY=value\n")
            f.write("# Another comment\n")
            f.write("OTHER=data\n")
            f.flush()

            env = parse_env_file(Path(f.name))

        self.assertEqual(len(env), 2)
        self.assertEqual(env["KEY"], "value")
        self.assertEqual(env["OTHER"], "data")

    def test_parse_ignores_empty_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("KEY=value\n")
            f.write("\n")
            f.write("  \n")
            f.write("OTHER=data\n")
            f.flush()

            env = parse_env_file(Path(f.name))

        self.assertEqual(len(env), 2)

    def test_parse_handles_values_with_equals(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("CONNECTION_STRING=host=localhost;port=5432\n")
            f.flush()

            env = parse_env_file(Path(f.name))

        self.assertEqual(env["CONNECTION_STRING"], "host=localhost;port=5432")


class TestReadEnvLines(unittest.TestCase):
    def test_read_lines(self):
        lines = read_env_lines(FIXTURES / "sample.env")

        self.assertEqual(len(lines), 6)
        self.assertEqual(lines[0], "PUID=1000")

    def test_read_nonexistent(self):
        lines = read_env_lines(Path("/nonexistent/.env"))

        self.assertEqual(lines, [])


class TestFindInsertPosition(unittest.TestCase):
    def test_find_position_by_prefix(self):
        lines = [
            "PUID=1000",
            "PGID=1000",
            "TZ=Europe/Paris",
            "DB_HOST=localhost",
            "DB_USER=admin",
        ]

        # DB_PASS should go after DB_USER (same DB_ prefix)
        pos = find_insert_position(lines, "DB_PASS", ["PUID", "PGID", "TZ", "DB_HOST", "DB_USER"])
        self.assertEqual(pos, 5)

    def test_find_position_no_prefix_match(self):
        lines = [
            "PUID=1000",
            "PGID=1000",
        ]

        # NEW_VAR has no matching prefix, goes at end
        pos = find_insert_position(lines, "NEW_VAR", ["PUID", "PGID"])
        self.assertEqual(pos, 2)

    def test_find_position_empty_lines(self):
        lines = []

        pos = find_insert_position(lines, "KEY", [])
        self.assertEqual(pos, 0)


class TestAddVarsToEnvFile(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_add_vars_to_existing_file(self):
        env_path = Path(self.temp_dir) / ".env"
        env_path.write_text("PUID=1000\nPGID=1000\n")

        add_vars_to_env_file(env_path, {"TZ": "Europe/Paris"}, ["TZ"])

        content = env_path.read_text()
        self.assertIn("TZ=Europe/Paris", content)

    def test_add_multiple_vars(self):
        env_path = Path(self.temp_dir) / ".env"
        env_path.write_text("PUID=1000\n")

        add_vars_to_env_file(
            env_path,
            {"PGID": "1000", "TZ": "Europe/Paris"},
            ["PGID", "TZ"]
        )

        content = env_path.read_text()
        self.assertIn("PGID=1000", content)
        self.assertIn("TZ=Europe/Paris", content)

    def test_add_vars_preserves_existing(self):
        env_path = Path(self.temp_dir) / ".env"
        env_path.write_text("EXISTING=value\n")

        add_vars_to_env_file(env_path, {"NEW": "data"}, ["NEW"])

        content = env_path.read_text()
        self.assertIn("EXISTING=value", content)
        self.assertIn("NEW=data", content)


if __name__ == "__main__":
    unittest.main()
