"""Tests for the `run` command: schema parsing, action lookup, exec building."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kompose import commands
from kompose.commands import (
    Action,
    _parse_action,
    _shell_quote,
    build_docker_exec,
    load_commands,
    resolve_action,
)


# ---------------------------------------------------------------------------
# Schema parsing
# ---------------------------------------------------------------------------


class TestParseAction(unittest.TestCase):
    def test_short_form_string(self):
        a = _parse_action("hub-upgrade", "cscli hub upgrade", "crowdsec", Path("/x"))
        self.assertEqual(a.name, "hub-upgrade")
        self.assertEqual(a.service, "crowdsec")
        self.assertEqual(a.container, "crowdsec")
        self.assertEqual(a.exec, "cscli hub upgrade")
        self.assertFalse(a.tty)

    def test_long_form_with_container_override(self):
        a = _parse_action(
            "rescan",
            {"container": "sonarr", "exec": "sonarr-cli rescan"},
            "servarr",
            Path("/x"),
        )
        self.assertEqual(a.container, "sonarr")
        self.assertEqual(a.exec, "sonarr-cli rescan")

    def test_long_form_with_tty(self):
        a = _parse_action("shell", {"exec": "bash", "tty": True}, "crowdsec", Path("/x"))
        self.assertEqual(a.container, "crowdsec")  # default to service
        self.assertTrue(a.tty)

    def test_long_form_missing_exec_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _parse_action("x", {"container": "foo"}, "svc", Path("/x"))
        self.assertIn("requires a non-empty `exec:`", str(ctx.exception))

    def test_invalid_value_type_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _parse_action("x", 42, "svc", Path("/x"))
        self.assertIn("must be a string or a mapping", str(ctx.exception))

    def test_tty_must_be_real_bool_not_string(self):
        # Guard against `tty: "false"` (YAML-quoted) silently enabling TTY.
        with self.assertRaises(ValueError) as ctx:
            _parse_action("x", {"exec": "cmd", "tty": "false"}, "svc", Path("/x"))
        self.assertIn("`tty:` must be true or false", str(ctx.exception))


# ---------------------------------------------------------------------------
# Loading (mono + multi)
# ---------------------------------------------------------------------------


class TestLoadCommands(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.host_dir = Path(self.tmpdir.name)
        self.kompose_dir = self.host_dir / ".kompose"
        self.kompose_dir.mkdir()
        # Patch the engine's host resolver to point at our tempdir.
        self._patch = mock.patch(
            "kompose.commands.get_kompose_dir", return_value=self.kompose_dir
        )
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmpdir.cleanup()

    def _write(self, rel: str, content: str) -> None:
        path = self.kompose_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_mono_file_short_form(self):
        self._write(
            "commands.yaml",
            "services:\n  crowdsec:\n    actions:\n      hub-upgrade: cscli hub upgrade\n",
        )
        actions = load_commands()
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].qualified_name, "crowdsec:hub-upgrade")
        self.assertEqual(actions[0].container, "crowdsec")

    def test_mono_and_multi_coexist(self):
        self._write(
            "commands.yaml",
            "services:\n  crowdsec:\n    actions:\n      hub-upgrade: cscli hub upgrade\n",
        )
        self._write(
            "commands/servarr.yaml",
            "actions:\n  sonarr-rescan:\n    container: sonarr\n    exec: sonarr-cli rescan\n",
        )
        actions = load_commands()
        names = sorted(a.qualified_name for a in actions)
        self.assertEqual(names, ["crowdsec:hub-upgrade", "servarr:sonarr-rescan"])

    def test_per_service_file_infers_service_from_filename(self):
        self._write(
            "commands/authelia.yaml",
            "actions:\n  reload: kill -HUP 1\n",
        )
        actions = load_commands()
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].service, "authelia")

    def test_multi_file_with_explicit_services_block(self):
        self._write(
            "commands/misc.yaml",
            "services:\n  redis:\n    actions:\n      info: redis-cli info\n",
        )
        actions = load_commands()
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].qualified_name, "redis:info")

    def test_duplicate_action_across_files_raises(self):
        self._write(
            "commands.yaml",
            "services:\n  crowdsec:\n    actions:\n      hub-upgrade: cscli hub upgrade\n",
        )
        self._write(
            "commands/crowdsec.yaml",
            "actions:\n  hub-upgrade: other cmd\n",
        )
        with self.assertRaises(ValueError) as ctx:
            load_commands()
        self.assertIn("Duplicate action", str(ctx.exception))

    def test_no_files_returns_empty(self):
        self.assertEqual(load_commands(), [])

    def test_top_level_not_mapping_raises(self):
        self._write("commands.yaml", "- one\n- two\n")
        with self.assertRaises(ValueError) as ctx:
            load_commands()
        self.assertIn("expected a YAML mapping", str(ctx.exception))


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def _act(svc: str, name: str, exec_: str = "cmd") -> Action:
    return Action(name=name, service=svc, container=svc, exec=exec_)


class TestResolveAction(unittest.TestCase):
    def test_unique_action_resolves_implicitly(self):
        actions = [_act("crowdsec", "hub-upgrade"), _act("servarr", "rescan")]
        self.assertEqual(resolve_action(actions, "hub-upgrade", None).service, "crowdsec")

    def test_explicit_service_action(self):
        actions = [_act("crowdsec", "hub-upgrade"), _act("authelia", "hub-upgrade")]
        self.assertEqual(
            resolve_action(actions, "authelia", "hub-upgrade").service, "authelia"
        )

    def test_ambiguous_implicit_raises_with_candidates(self):
        actions = [_act("crowdsec", "reload"), _act("authelia", "reload")]
        with self.assertRaises(LookupError) as ctx:
            resolve_action(actions, "reload", None)
        msg = str(ctx.exception)
        self.assertIn("ambiguous", msg)
        self.assertIn("crowdsec:reload", msg)
        self.assertIn("authelia:reload", msg)

    def test_missing_action_raises(self):
        actions = [_act("crowdsec", "hub-upgrade")]
        with self.assertRaises(LookupError):
            resolve_action(actions, "nope", None)

    def test_explicit_form_missing_action_lists_available(self):
        actions = [_act("crowdsec", "hub-upgrade"), _act("crowdsec", "shell")]
        with self.assertRaises(LookupError) as ctx:
            resolve_action(actions, "crowdsec", "nope")
        self.assertIn("hub-upgrade", str(ctx.exception))
        self.assertIn("shell", str(ctx.exception))


# ---------------------------------------------------------------------------
# Exec building
# ---------------------------------------------------------------------------


class TestShellQuote(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(_shell_quote("abc"), "'abc'")

    def test_empty(self):
        self.assertEqual(_shell_quote(""), "''")

    def test_with_single_quote(self):
        self.assertEqual(_shell_quote("it's"), "'it'\\''s'")


class TestBuildDockerExec(unittest.TestCase):
    def test_basic(self):
        a = _act("crowdsec", "hub-upgrade", exec_="cscli hub upgrade")
        cmd = build_docker_exec(a, [])
        self.assertEqual(cmd, ["docker", "exec", "-i", "crowdsec", "sh", "-c", "cscli hub upgrade"])

    def test_forwarded_args_appended_and_quoted(self):
        a = _act("crowdsec", "ban", exec_="cscli decisions add --ip")
        cmd = build_docker_exec(a, ["1.2.3.4", "--duration", "10m"])
        # forwarded args appear as quoted tokens after the base command
        self.assertEqual(
            cmd[-1],
            "cscli decisions add --ip '1.2.3.4' '--duration' '10m'",
        )

    @mock.patch("sys.stdin.isatty", return_value=True)
    def test_tty_action_with_tty_stdin(self, _):
        a = Action(name="shell", service="crowdsec", container="crowdsec", exec="bash", tty=True)
        cmd = build_docker_exec(a, [])
        self.assertIn("-it", cmd)

    @mock.patch("sys.stdin.isatty", return_value=False)
    def test_tty_action_without_tty_stdin_falls_back_to_i(self, _):
        a = Action(name="shell", service="crowdsec", container="crowdsec", exec="bash", tty=True)
        cmd = build_docker_exec(a, [])
        self.assertIn("-i", cmd)
        self.assertNotIn("-it", cmd)


# ---------------------------------------------------------------------------
# cmd_run dispatch
# ---------------------------------------------------------------------------


class TestCmdRun(unittest.TestCase):
    def _args(self, **kw):
        ns = mock.MagicMock()
        ns.host = None
        ns.first = kw.get("first")
        ns.second = kw.get("second")
        ns.verbose = kw.get("verbose", False)
        ns.forwarded = kw.get("forwarded", [])
        return ns

    @mock.patch("kompose.commands.subprocess.run")
    @mock.patch("kompose.commands.load_commands")
    def test_runs_unique_action(self, mock_load, mock_run):
        mock_load.return_value = [_act("crowdsec", "hub-upgrade", exec_="cscli hub upgrade")]
        mock_run.return_value = mock.MagicMock(returncode=0)
        rc = commands.cmd_run(self._args(first="hub-upgrade"))
        self.assertEqual(rc, 0)
        called_cmd = mock_run.call_args[0][0]
        self.assertEqual(called_cmd[:3], ["docker", "exec", "-i"])
        self.assertEqual(called_cmd[3], "crowdsec")

    @mock.patch("kompose.commands.subprocess.run")
    @mock.patch("kompose.commands.load_commands")
    def test_listing_no_args(self, mock_load, mock_run):
        mock_load.return_value = [_act("crowdsec", "hub-upgrade")]
        rc = commands.cmd_run(self._args())
        self.assertEqual(rc, 0)
        mock_run.assert_not_called()

    @mock.patch("kompose.commands.load_commands")
    def test_ambiguous_action_returns_error(self, mock_load):
        mock_load.return_value = [_act("a", "reload"), _act("b", "reload")]
        rc = commands.cmd_run(self._args(first="reload"))
        self.assertEqual(rc, 2)

    @mock.patch("kompose.commands.subprocess.run")
    @mock.patch("kompose.commands.load_commands")
    def test_single_service_arg_lists_its_actions(self, mock_load, mock_run):
        mock_load.return_value = [
            _act("crowdsec", "hub-upgrade"),
            _act("crowdsec", "shell"),
        ]
        rc = commands.cmd_run(self._args(first="crowdsec"))
        self.assertEqual(rc, 0)
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
