"""Tests for config module — paths + precedence chain."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kompose import config
from kompose.config import (
    DEFAULT_HOST,
    WORKSPACE_DIR,
    _HARDCODED_HOST,
    _HARDCODED_WORKSPACE,
    _resolve,
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


class TestResolutionChain(unittest.TestCase):
    """Verify the precedence: env var > file config > hardcoded fallback."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.xdg = Path(self.tmpdir.name)
        # Point XDG at the tempdir and clear the kompose env vars so each
        # subtest starts from a clean precedence state.
        self.env_patch = mock.patch.dict(
            "os.environ",
            {"XDG_CONFIG_HOME": str(self.xdg)},
            clear=False,
        )
        self.env_patch.start()
        for var in ("KOMPOSE_WORKSPACE", "KOMPOSE_HOST"):
            os_environ_pop = mock.patch.dict("os.environ", {var: ""}, clear=False)
            os_environ_pop.start()
            self.addCleanup(os_environ_pop.stop)

    def tearDown(self):
        self.env_patch.stop()
        self.tmpdir.cleanup()

    def _write_config(self, content: str) -> None:
        cfg_dir = self.xdg / "kompose"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "config.yaml").write_text(content)

    def test_hardcoded_fallback_when_nothing_set(self):
        workspace, host = _resolve()
        self.assertEqual(workspace, Path(_HARDCODED_WORKSPACE))
        self.assertEqual(host, _HARDCODED_HOST)

    def test_xdg_config_file_overrides_fallback(self):
        self._write_config("workspace: /from/file\nhost: filehost\n")
        workspace, host = _resolve()
        self.assertEqual(workspace, Path("/from/file"))
        self.assertEqual(host, "filehost")

    def test_env_var_overrides_file(self):
        self._write_config("workspace: /from/file\nhost: filehost\n")
        with mock.patch.dict(
            "os.environ",
            {"KOMPOSE_WORKSPACE": "/from/env", "KOMPOSE_HOST": "envhost"},
        ):
            workspace, host = _resolve()
        self.assertEqual(workspace, Path("/from/env"))
        self.assertEqual(host, "envhost")

    def test_partial_file_falls_back_per_key(self):
        # Only workspace in file → host comes from hardcoded fallback
        self._write_config("workspace: /from/file\n")
        workspace, host = _resolve()
        self.assertEqual(workspace, Path("/from/file"))
        self.assertEqual(host, _HARDCODED_HOST)

    def test_malformed_yaml_silently_falls_back(self):
        # A broken config must not crash the CLI on every command.
        self._write_config("workspace: [unclosed\n")
        workspace, host = _resolve()
        self.assertEqual(workspace, Path(_HARDCODED_WORKSPACE))
        self.assertEqual(host, _HARDCODED_HOST)

    def test_non_mapping_yaml_treated_as_no_config(self):
        self._write_config("- just\n- a\n- list\n")
        workspace, host = _resolve()
        self.assertEqual(workspace, Path(_HARDCODED_WORKSPACE))
        self.assertEqual(host, _HARDCODED_HOST)


if __name__ == "__main__":
    unittest.main()
