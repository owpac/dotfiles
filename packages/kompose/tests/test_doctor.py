"""Tests for `kompose doctor` — config validation."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kompose import doctor
from kompose._engine import SEVERITY_ERROR, SEVERITY_WARNING
from kompose.doctor import (
    DoctorFinding,
    _compose_containers,
    _render,
    check_commands_yaml,
    check_general,
    check_rules_yaml,
    cmd_doctor,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


class _DoctorTestCase(unittest.TestCase):
    """Tempdir-backed fixture mirroring `<host>/{.kompose,<service>/...}`."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmpdir.name)
        self.host = "fakehost"
        self.host_dir = self.workspace / self.host
        self.kompose_dir = self.host_dir / ".kompose"
        self.host_dir.mkdir()
        self.kompose_dir.mkdir()

        # Point every config-resolving helper at the tempdir.
        self._patches = [
            mock.patch("kompose.config.WORKSPACE_DIR", self.workspace),
            mock.patch("kompose.config.DEFAULT_HOST", self.host),
            mock.patch("kompose._engine.get_host_dir", return_value=self.host_dir),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmpdir.cleanup()

    def _write_kompose(self, rel: str, content: str) -> Path:
        path = self.kompose_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def _write_service(self, name: str, containers: list[str]) -> Path:
        svc_dir = self.host_dir / name
        svc_dir.mkdir(exist_ok=True)
        services_block = "\n".join(f"  {c}:\n    image: alpine" for c in containers)
        (svc_dir / "compose.yml").write_text(f"services:\n{services_block}\n")
        return svc_dir


# ---------------------------------------------------------------------------
# _compose_containers
# ---------------------------------------------------------------------------


class TestComposeContainers(unittest.TestCase):
    def test_reads_service_names(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            f.write("services:\n  sonarr:\n    image: x\n  radarr:\n    image: y\n")
            path = Path(f.name)
        try:
            self.assertEqual(_compose_containers(path), {"sonarr", "radarr"})
        finally:
            path.unlink()

    def test_missing_file_returns_empty(self):
        self.assertEqual(_compose_containers(Path("/nope/missing.yml")), set())

    def test_malformed_yaml_returns_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            f.write("services:\n  - this isn't valid\nstructure: [\n")
            path = Path(f.name)
        try:
            self.assertEqual(_compose_containers(path), set())
        finally:
            path.unlink()


# ---------------------------------------------------------------------------
# check_rules_yaml
# ---------------------------------------------------------------------------


class TestCheckRulesYaml(_DoctorTestCase):
    def _valid_rules(self) -> str:
        return (
            "rules:\n"
            "  - name: logging-driver\n"
            "    category: logging\n"
            "    type: substring_required\n"
            "    params:\n"
            "      required:\n"
            "        - 'logging:'\n"
        )

    def test_no_kompose_dir_returns_empty(self):
        # check_rules_yaml swallows FileNotFoundError to defer to check_general
        import shutil
        shutil.rmtree(self.kompose_dir)
        self.assertEqual(check_rules_yaml(), [])

    def test_clean_rules_no_findings(self):
        self._write_kompose("rules.yaml", self._valid_rules())
        self.assertEqual(check_rules_yaml(), [])

    def test_handler_not_importable_is_error(self):
        self._write_kompose(
            "rules.yaml",
            "rules:\n  - name: x\n    category: foo\n    handler: not_a_real_handler\n",
        )
        findings = check_rules_yaml()
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, SEVERITY_ERROR)
        self.assertIn("not_a_real_handler", findings[0].message)

    def test_unknown_builtin_type_is_error(self):
        self._write_kompose(
            "rules.yaml",
            "rules:\n  - name: x\n    category: foo\n    type: not_a_real_type\n",
        )
        findings = check_rules_yaml()
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, SEVERITY_ERROR)
        self.assertIn("not_a_real_type", findings[0].message)

    def test_excluded_service_missing_is_warning(self):
        self._write_kompose(
            "rules.yaml",
            "rules:\n"
            "  - name: x\n"
            "    category: foo\n"
            "    type: substring_required\n"
            "    exclude:\n"
            "      - ghost-service\n"
            "    params:\n"
            "      required: ['x']\n",
        )
        findings = check_rules_yaml()
        warnings = [f for f in findings if f.severity == SEVERITY_WARNING]
        self.assertTrue(any("ghost-service" in f.message for f in warnings))

    def test_schema_invalid_is_error(self):
        self._write_kompose("rules.yaml", "rules:\n  - missing-name-and-category: x\n")
        findings = check_rules_yaml()
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, SEVERITY_ERROR)


# ---------------------------------------------------------------------------
# check_commands_yaml
# ---------------------------------------------------------------------------


class TestCheckCommandsYaml(_DoctorTestCase):
    def test_no_commands_no_findings(self):
        self.assertEqual(check_commands_yaml(), [])

    def test_clean_commands_no_findings(self):
        self._write_service("crowdsec", ["crowdsec"])
        self._write_kompose(
            "commands.yaml",
            "services:\n  crowdsec:\n    actions:\n      hub-upgrade: cscli hub upgrade\n",
        )
        self.assertEqual(check_commands_yaml(), [])

    def test_missing_service_dir_is_error(self):
        self._write_kompose(
            "commands.yaml",
            "services:\n  nosvc:\n    actions:\n      x: echo hi\n",
        )
        findings = check_commands_yaml()
        self.assertTrue(any(f.severity == SEVERITY_ERROR and "no compose.yml" in f.message for f in findings))

    def test_container_not_declared_is_error(self):
        self._write_service("servarr", ["sonarr", "radarr"])
        self._write_kompose(
            "commands.yaml",
            "services:\n  servarr:\n    actions:\n"
            "      ghost:\n        container: lidarr\n        exec: echo hi\n",
        )
        findings = check_commands_yaml()
        errors = [f for f in findings if f.severity == SEVERITY_ERROR]
        self.assertEqual(len(errors), 1)
        self.assertIn("lidarr", errors[0].message)
        self.assertIn("sonarr", errors[0].message)  # context list

    def test_action_name_shadows_subcommand_is_warning(self):
        self._write_service("crowdsec", ["crowdsec"])
        self._write_kompose(
            "commands.yaml",
            "services:\n  crowdsec:\n    actions:\n      restart: echo hi\n",
        )
        findings = check_commands_yaml()
        warnings = [f for f in findings if f.severity == SEVERITY_WARNING]
        self.assertTrue(any("'restart'" in f.message for f in warnings))

    def test_schema_invalid_is_error(self):
        self._write_kompose("commands.yaml", "services: not-a-mapping\n")
        findings = check_commands_yaml()
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, SEVERITY_ERROR)


# ---------------------------------------------------------------------------
# check_general
# ---------------------------------------------------------------------------


class TestCheckGeneral(_DoctorTestCase):
    def test_kompose_dir_present_no_findings(self):
        self.assertEqual(check_general(), [])

    def test_kompose_dir_missing_is_warning(self):
        import shutil
        shutil.rmtree(self.kompose_dir)
        findings = check_general()
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, SEVERITY_WARNING)


# ---------------------------------------------------------------------------
# _render
# ---------------------------------------------------------------------------


class TestRender(unittest.TestCase):
    def test_empty_findings_prints_clean(self):
        out = _render([])
        self.assertIn("looks good", out)

    def test_grouping_and_icons(self):
        findings = [
            DoctorFinding(SEVERITY_ERROR, "commands.yaml", "container missing", "crowdsec:x"),
            DoctorFinding(SEVERITY_WARNING, "commands.yaml", "shadows builtin", "crowdsec:fix"),
            DoctorFinding(SEVERITY_ERROR, "rules.yaml", "handler not found", "rule 'a'"),
        ]
        out = _render(findings)
        self.assertIn("commands.yaml", out)
        self.assertIn("rules.yaml", out)
        self.assertIn("✗", out)
        self.assertIn("⚠", out)
        self.assertIn("2 errors", out)
        self.assertIn("1 warning", out)


# ---------------------------------------------------------------------------
# cmd_doctor dispatch
# ---------------------------------------------------------------------------


class TestCmdDoctor(_DoctorTestCase):
    def _args(self, **kw):
        ns = mock.MagicMock()
        ns.host = None
        ns.rules = kw.get("rules", False)
        ns.commands = kw.get("commands", False)
        return ns

    def test_clean_config_returns_zero(self):
        # No rules.yaml, no commands.yaml — just check_general passes
        # (kompose_dir exists from setUp).
        rc = cmd_doctor(self._args())
        self.assertEqual(rc, 0)

    def test_error_returns_one(self):
        self._write_kompose(
            "commands.yaml",
            "services:\n  ghost:\n    actions:\n      x: echo hi\n",
        )
        rc = cmd_doctor(self._args())
        self.assertEqual(rc, 1)

    def test_only_rules_skips_commands(self):
        # Add a commands.yaml error that --rules should ignore.
        self._write_kompose(
            "commands.yaml",
            "services:\n  ghost:\n    actions:\n      x: echo hi\n",
        )
        rc = cmd_doctor(self._args(rules=True))
        self.assertEqual(rc, 0)

    def test_only_commands_skips_rules(self):
        # Add a rules.yaml error that --commands should ignore.
        self._write_kompose(
            "rules.yaml",
            "rules:\n  - name: x\n    category: foo\n    handler: missing\n",
        )
        rc = cmd_doctor(self._args(commands=True))
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
