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
    remove_vars_from_env_file,
    _parse_commented_vars,
    build_example_content,
    fix_trailing_newline,
    rebuild_example,
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

    def test_parse_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("")
            f.flush()

            env = parse_env_file(Path(f.name))

        self.assertEqual(env, {})

    def test_parse_lowercase_keys(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("my_key=value\n")
            f.flush()

            env = parse_env_file(Path(f.name))

        self.assertEqual(env["my_key"], "value")

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

    def test_strips_trailing_whitespace(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("KEY=value   \n")
            f.write("OTHER=data\t\n")
            f.flush()

            lines = read_env_lines(Path(f.name))

        self.assertEqual(lines, ["KEY=value", "OTHER=data"])

    def test_reads_file_without_trailing_newline(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("KEY=value\nOTHER=data")
            f.flush()

            lines = read_env_lines(Path(f.name))

        self.assertEqual(lines, ["KEY=value", "OTHER=data"])

    def test_preserves_comments_and_blank_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("# Section\n")
            f.write("KEY=value\n")
            f.write("\n")
            f.write("OTHER=data\n")
            f.flush()

            lines = read_env_lines(Path(f.name))

        self.assertEqual(lines, ["# Section", "KEY=value", "", "OTHER=data"])


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

    def test_find_position_skips_comments_and_blanks(self):
        lines = [
            "# Section",
            "DB_HOST=localhost",
            "",
            "DB_USER=admin",
        ]

        pos = find_insert_position(lines, "DB_PASS", ["DB_HOST", "DB_USER"])
        self.assertEqual(pos, 4)

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

    def test_add_vars_ensures_trailing_newline(self):
        env_path = Path(self.temp_dir) / ".env"
        env_path.write_text("PUID=1000\n")

        add_vars_to_env_file(env_path, {"TZ": "Europe/Paris"}, ["TZ"])

        self.assertTrue(env_path.read_text().endswith("\n"))

    def test_add_vars_preserves_existing(self):
        env_path = Path(self.temp_dir) / ".env"
        env_path.write_text("EXISTING=value\n")

        add_vars_to_env_file(env_path, {"NEW": "data"}, ["NEW"])

        content = env_path.read_text()
        self.assertIn("EXISTING=value", content)
        self.assertIn("NEW=data", content)


class TestRemoveVarsFromEnvFile(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_remove_single_var(self):
        env_path = Path(self.temp_dir) / ".env"
        env_path.write_text("PUID=1000\nPGID=1000\nTZ=Europe/Paris\n")

        remove_vars_from_env_file(env_path, {"PGID"})

        content = env_path.read_text()
        self.assertIn("PUID=1000", content)
        self.assertNotIn("PGID", content)
        self.assertIn("TZ=Europe/Paris", content)

    def test_remove_multiple_vars(self):
        env_path = Path(self.temp_dir) / ".env"
        env_path.write_text("A=1\nB=2\nC=3\nD=4\n")

        remove_vars_from_env_file(env_path, {"B", "D"})

        content = env_path.read_text()
        self.assertIn("A=1", content)
        self.assertNotIn("B=", content)
        self.assertIn("C=3", content)
        self.assertNotIn("D=", content)

    def test_remove_nonexistent_var(self):
        env_path = Path(self.temp_dir) / ".env"
        env_path.write_text("PUID=1000\n")

        remove_vars_from_env_file(env_path, {"NONEXISTENT"})

        content = env_path.read_text()
        self.assertIn("PUID=1000", content)

    def test_remove_all_vars_leaves_trailing_newline(self):
        env_path = Path(self.temp_dir) / ".env"
        env_path.write_text("A=1\nB=2\n")

        remove_vars_from_env_file(env_path, {"A", "B"})

        self.assertTrue(env_path.read_text().endswith("\n"))

    def test_remove_ensures_trailing_newline(self):
        env_path = Path(self.temp_dir) / ".env"
        env_path.write_text("A=1\nB=2\n")

        remove_vars_from_env_file(env_path, {"B"})

        self.assertTrue(env_path.read_text().endswith("\n"))

    def test_remove_preserves_comments(self):
        env_path = Path(self.temp_dir) / ".env"
        env_path.write_text("# Comment\nPUID=1000\nPGID=1000\n")

        remove_vars_from_env_file(env_path, {"PGID"})

        content = env_path.read_text()
        self.assertIn("# Comment", content)
        self.assertIn("PUID=1000", content)
        self.assertNotIn("PGID", content)


class TestParseCommentedVars(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_parses_commented_vars(self):
        path = Path(self.temp_dir) / ".env"
        path.write_text("# API_KEY=secret\n# OTHER=value\nKEY=active\n")

        result = _parse_commented_vars(path)

        self.assertEqual(result, {"API_KEY": "secret", "OTHER": "value"})

    def test_ignores_plain_comments(self):
        path = Path(self.temp_dir) / ".env"
        path.write_text("# This is a header\nKEY=value\n")

        result = _parse_commented_vars(path)

        self.assertEqual(result, {})

    def test_ignores_empty_value_comments(self):
        path = Path(self.temp_dir) / ".env"
        path.write_text("# KEY=\nOTHER=value\n")

        result = _parse_commented_vars(path)

        self.assertEqual(result, {})

    def test_multiple_spaces_after_hash(self):
        path = Path(self.temp_dir) / ".env"
        path.write_text("#   API_KEY=secret\n")

        result = _parse_commented_vars(path)

        self.assertEqual(result, {"API_KEY": "secret"})

    def test_nonexistent_file(self):
        result = _parse_commented_vars(Path("/nonexistent/.env"))

        self.assertEqual(result, {})


class TestFixTrailingNewline(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_adds_newline_when_missing(self):
        path = Path(self.temp_dir) / ".env"
        path.write_text("KEY=value")

        changed = fix_trailing_newline(path)

        self.assertTrue(changed)
        self.assertEqual(path.read_text(), "KEY=value\n")

    def test_no_change_when_present(self):
        path = Path(self.temp_dir) / ".env"
        path.write_text("KEY=value\n")

        changed = fix_trailing_newline(path)

        self.assertFalse(changed)

    def test_no_change_on_empty_file(self):
        path = Path(self.temp_dir) / ".env"
        path.write_text("")

        changed = fix_trailing_newline(path)

        self.assertFalse(changed)

    def test_multiline_without_newline(self):
        path = Path(self.temp_dir) / ".env"
        path.write_text("KEY=value\nOTHER=data")

        changed = fix_trailing_newline(path)

        self.assertTrue(changed)
        self.assertEqual(path.read_text(), "KEY=value\nOTHER=data\n")

    def test_does_not_double_newline(self):
        path = Path(self.temp_dir) / ".env"
        path.write_text("KEY=value\n\n")

        changed = fix_trailing_newline(path)

        self.assertFalse(changed)


class TestBuildExampleContent(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_copies_comments_and_blank_lines(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("# General\nPUID=1000\nPGID=1000\n\n# Database\nDB_HOST=localhost\n")
        example_path.write_text("PUID=''\nPGID=''\nDB_HOST=''\n")

        content = build_example_content(env_path, example_path)

        self.assertEqual(content, "# General\nPUID=''\nPGID=''\n\n# Database\nDB_HOST=''\n")

    def test_new_vars_get_empty_value(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("EXISTING=value\nNEW_VAR=secret\n")
        example_path.write_text("EXISTING=''\n")

        content = build_example_content(env_path, example_path)

        self.assertEqual(content, "EXISTING=''\nNEW_VAR=''\n")

    def test_preserves_existing_example_values(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("DB_HOST=prod.db.com\n")
        example_path.write_text("DB_HOST=localhost\n")

        content = build_example_content(env_path, example_path)

        self.assertEqual(content, "DB_HOST=localhost\n")

    def test_empty_env_with_nonempty_example(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("")
        example_path.write_text("KEY=''\nOTHER=''\n")

        content = build_example_content(env_path, example_path)

        # .env is structural reference: empty .env = empty output
        self.assertEqual(content, "")

    def test_env_without_trailing_newline(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("KEY=value\nOTHER=data")
        example_path.write_text("KEY=''\nOTHER=''\n")

        content = build_example_content(env_path, example_path)

        # Output always has trailing newline
        self.assertEqual(content, "KEY=''\nOTHER=''\n")

    def test_empty_env_produces_empty_content(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("")
        example_path.write_text("")

        content = build_example_content(env_path, example_path)

        self.assertEqual(content, "")

    def test_multiple_comment_sections(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text(
            "# General\nPUID=1000\nPGID=1000\n\n"
            "# App\nAPP_KEY=secret\nAPP_DEBUG=true\n\n"
            "# DB\nDB_HOST=prod\n"
        )
        example_path.write_text("PUID=''\nPGID=''\nAPP_KEY=''\nAPP_DEBUG=''\nDB_HOST=''\n")

        content = build_example_content(env_path, example_path)

        self.assertEqual(
            content,
            "# General\nPUID=''\nPGID=''\n\n"
            "# App\nAPP_KEY=''\nAPP_DEBUG=''\n\n"
            "# DB\nDB_HOST=''\n"
        )

    def test_ignores_trailing_whitespace_in_env(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("KEY=value   \nOTHER=data\t\n")
        example_path.write_text("KEY=''\nOTHER=''\n")

        content = build_example_content(env_path, example_path)

        self.assertEqual(content, "KEY=''\nOTHER=''\n")

    def test_nonexistent_example_uses_empty_values(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("KEY=value\nOTHER=data\n")
        # example_path does not exist

        content = build_example_content(env_path, example_path)

        self.assertEqual(content, "KEY=''\nOTHER=''\n")

    def test_sanitizes_commented_out_env_vars(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("# SECRET_KEY=my_actual_secret_123\nKEY=value\n")
        example_path.write_text("KEY=''\n")

        content = build_example_content(env_path, example_path)

        self.assertEqual(content, "# SECRET_KEY=''\nKEY=''\n")

    def test_sanitizes_commented_out_vars_no_space_after_hash(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("#API_KEY=secret_token\nKEY=value\n")
        example_path.write_text("KEY=''\n")

        content = build_example_content(env_path, example_path)

        self.assertEqual(content, "#API_KEY=''\nKEY=''\n")

    def test_preserves_commented_out_vars_with_empty_value(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("# OPTIONAL_KEY=\nKEY=value\n")
        example_path.write_text("KEY=''\n")

        content = build_example_content(env_path, example_path)

        # Empty value (# KEY=) is not sensitive, kept as-is
        self.assertEqual(content, "# OPTIONAL_KEY=\nKEY=''\n")

    def test_preserves_plain_comments(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("# This is a section header\n# Another description line\nKEY=value\n")
        example_path.write_text("KEY=''\n")

        content = build_example_content(env_path, example_path)

        self.assertEqual(content, "# This is a section header\n# Another description line\nKEY=''\n")

    def test_sanitizes_new_commented_out_vars(self):
        """Commented vars not in .env.example are sanitized to ''."""
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text(
            "# Homepage widgets\n"
            "# HOMEPAGE_VAR_SONARR_KEY=abc123secret\n"
            "# HOMEPAGE_VAR_RADARR_KEY=def456secret\n"
            "HOMEPAGE_PORT=3000\n"
        )
        example_path.write_text("HOMEPAGE_PORT=''\n")

        content = build_example_content(env_path, example_path)

        self.assertEqual(
            content,
            "# Homepage widgets\n"
            "# HOMEPAGE_VAR_SONARR_KEY=''\n"
            "# HOMEPAGE_VAR_RADARR_KEY=''\n"
            "HOMEPAGE_PORT=''\n"
        )

    def test_preserves_existing_commented_out_vars(self):
        """Commented vars already in .env.example keep their value."""
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text(
            "# HOMEPAGE_VAR_SONARR_KEY=abc123secret\n"
            "# HOMEPAGE_VAR_RADARR_KEY=def456secret\n"
            "HOMEPAGE_PORT=3000\n"
        )
        example_path.write_text(
            "# HOMEPAGE_VAR_SONARR_KEY=<sonarr_api_key>\n"
            "# HOMEPAGE_VAR_RADARR_KEY=<radarr_api_key>\n"
            "HOMEPAGE_PORT=''\n"
        )

        content = build_example_content(env_path, example_path)

        self.assertEqual(
            content,
            "# HOMEPAGE_VAR_SONARR_KEY=<sonarr_api_key>\n"
            "# HOMEPAGE_VAR_RADARR_KEY=<radarr_api_key>\n"
            "HOMEPAGE_PORT=''\n"
        )


class TestRebuildExample(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_rebuild_when_structure_differs(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("# Section\nKEY=value\n\nOTHER=data\n")
        example_path.write_text("KEY=''\nOTHER=''\n")

        changed = rebuild_example(env_path, example_path)

        self.assertTrue(changed)
        self.assertEqual(example_path.read_text(), "# Section\nKEY=''\n\nOTHER=''\n")

    def test_no_rebuild_when_identical(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("# Section\nKEY=value\n")
        example_path.write_text("# Section\nKEY=''\n")

        changed = rebuild_example(env_path, example_path)

        self.assertFalse(changed)

    def test_rebuild_reorders_to_match_env(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("B=2\nA=1\n")
        example_path.write_text("A=''\nB=''\n")

        changed = rebuild_example(env_path, example_path)

        self.assertTrue(changed)
        self.assertEqual(example_path.read_text(), "B=''\nA=''\n")

    def test_rebuild_adds_missing_comments(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("# Server\nHOST=0.0.0.0\nPORT=8080\n\n# Auth\nSECRET=abc\n")
        example_path.write_text("HOST=''\nPORT=''\nSECRET=''\n")

        changed = rebuild_example(env_path, example_path)

        self.assertTrue(changed)
        self.assertEqual(
            example_path.read_text(),
            "# Server\nHOST=''\nPORT=''\n\n# Auth\nSECRET=''\n"
        )

    def test_rebuild_strips_trailing_whitespace(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("KEY=value\n")
        example_path.write_text("KEY=''   \n")

        changed = rebuild_example(env_path, example_path)

        self.assertTrue(changed)
        self.assertEqual(example_path.read_text(), "KEY=''\n")

    def test_rebuild_creates_example_if_missing(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("KEY=value\n")
        # example_path does not exist

        changed = rebuild_example(env_path, example_path)

        self.assertTrue(changed)
        self.assertEqual(example_path.read_text(), "KEY=''\n")

    def test_rebuild_sanitizes_new_commented_out_vars(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("# API_KEY=real_secret\nKEY=value\n")
        example_path.write_text("KEY=''\n")  # no commented API_KEY in example

        changed = rebuild_example(env_path, example_path)

        self.assertTrue(changed)
        self.assertEqual(example_path.read_text(), "# API_KEY=''\nKEY=''\n")

    def test_no_rebuild_when_both_empty(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("")
        example_path.write_text("")

        changed = rebuild_example(env_path, example_path)

        self.assertFalse(changed)

    def test_rebuild_fixes_missing_trailing_newline_in_example(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("KEY=value\n")
        example_path.write_text("KEY=''")  # no trailing newline

        changed = rebuild_example(env_path, example_path)

        self.assertTrue(changed)
        self.assertEqual(example_path.read_text(), "KEY=''\n")

    def test_rebuild_preserves_existing_commented_out_vars(self):
        env_path = Path(self.temp_dir) / ".env"
        example_path = Path(self.temp_dir) / ".env.example"
        env_path.write_text("# API_KEY=real_secret\nKEY=value\n")
        example_path.write_text("# API_KEY=<your_api_key>\nKEY=''\n")

        changed = rebuild_example(env_path, example_path)

        self.assertFalse(changed)
        self.assertEqual(example_path.read_text(), "# API_KEY=<your_api_key>\nKEY=''\n")


if __name__ == "__main__":
    unittest.main()
