"""Tests for the lint engine: YAML loading, dispatch, RuleSpec validation."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kompose import _engine
from kompose._engine import (
    LintContext,
    RuleSpec,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    lint_service,
    load_rules,
    resolve_handler,
    resolve_notices,
    run_notices,
    run_rule,
)


class TestRuleSpecValidation(unittest.TestCase):
    def test_requires_type_or_handler(self):
        with self.assertRaises(ValueError):
            RuleSpec(name="r", category="c")

    def test_rejects_both_type_and_handler(self):
        with self.assertRaises(ValueError):
            RuleSpec(name="r", category="c", type="substring_required", handler="x")

    def test_rejects_invalid_severity(self):
        with self.assertRaises(ValueError):
            RuleSpec(name="r", category="c", type="substring_required", severity="critical")

    def test_default_severity_is_error(self):
        spec = RuleSpec(name="r", category="c", type="substring_required")
        self.assertEqual(spec.severity, SEVERITY_ERROR)

    def test_warning_severity_accepted(self):
        spec = RuleSpec(name="r", category="c", type="substring_required", severity=SEVERITY_WARNING)
        self.assertEqual(spec.severity, SEVERITY_WARNING)


class TestResolveHandler(unittest.TestCase):
    def test_resolves_builtin_type(self):
        spec = RuleSpec(name="r", category="c", type="substring_required")
        fn = resolve_handler(spec)
        self.assertTrue(callable(fn))

    def test_unknown_builtin_type_raises(self):
        spec = RuleSpec(name="r", category="c", type="does_not_exist")
        with self.assertRaises(ValueError):
            resolve_handler(spec)

    def test_resolves_handler_module(self):
        spec = RuleSpec(name="r", category="c", handler="traefik_router_naming")
        fn = resolve_handler(spec)
        self.assertTrue(callable(fn))

    def test_unknown_handler_raises(self):
        spec = RuleSpec(name="r", category="c", handler="does_not_exist")
        with self.assertRaises(ValueError):
            resolve_handler(spec)


class TestRunRule(unittest.TestCase):
    def _ctx(self, content: str = "") -> LintContext:
        return LintContext(
            service_name="svc",
            compose_path=Path("/tmp/compose.yml"),
            content=content,
            parsed={},
            globals={},
        )

    def test_builtin_dispatch(self):
        spec = RuleSpec(
            name="r",
            category="c",
            type="substring_required",
            params={"required": ["needle"]},
        )
        ctx = self._ctx("haystack")
        issues = run_rule(spec, ctx)
        self.assertEqual(len(issues), 1)

    def test_handler_dispatch(self):
        spec = RuleSpec(name="r", category="c", handler="reverse_proxy_network")
        ctx = self._ctx("image: x")
        issues = run_rule(spec, ctx)
        self.assertEqual(len(issues), 1)


class TestLoadRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kompose_dir = Path(self.tmp.name) / ".kompose"
        self.kompose_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _patch_kompose_dir(self):
        return mock.patch.object(
            _engine, "get_kompose_dir", return_value=self.kompose_dir
        )

    def test_mono_file(self):
        (self.kompose_dir / "rules.yaml").write_text(
            "globals:\n"
            "  public_domain: x.com\n"
            "rules:\n"
            "  - name: r1\n"
            "    category: cat\n"
            "    type: substring_required\n"
            "    params:\n"
            "      required: ['foo']\n"
        )
        with self._patch_kompose_dir():
            globals_dict, rules = load_rules()
        self.assertEqual(globals_dict["public_domain"], "x.com")
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].name, "r1")

    def test_multi_file(self):
        (self.kompose_dir / "globals.yaml").write_text("public_domain: y.com\n")
        rules_dir = self.kompose_dir / "rules"
        rules_dir.mkdir()
        (rules_dir / "r1.yaml").write_text(
            "name: r1\n"
            "category: cat\n"
            "type: substring_required\n"
            "params:\n"
            "  required: ['foo']\n"
        )
        (rules_dir / "r2.yaml").write_text(
            "rules:\n"
            "  - name: r2\n"
            "    category: cat\n"
            "    handler: reverse_proxy_network\n"
        )
        with self._patch_kompose_dir():
            globals_dict, rules = load_rules()
        self.assertEqual(globals_dict["public_domain"], "y.com")
        names = sorted(r.name for r in rules)
        self.assertEqual(names, ["r1", "r2"])

    def test_duplicate_rule_name_raises(self):
        (self.kompose_dir / "rules.yaml").write_text(
            "rules:\n"
            "  - name: r1\n"
            "    category: cat\n"
            "    type: substring_required\n"
        )
        rules_dir = self.kompose_dir / "rules"
        rules_dir.mkdir()
        (rules_dir / "dup.yaml").write_text(
            "name: r1\n"
            "category: cat\n"
            "handler: reverse_proxy_network\n"
        )
        with self._patch_kompose_dir():
            with self.assertRaises(ValueError):
                load_rules()

    def test_missing_kompose_dir_raises(self):
        bogus = Path(self.tmp.name) / "does-not-exist"
        with mock.patch.object(_engine, "get_kompose_dir", return_value=bogus):
            with self.assertRaises(FileNotFoundError):
                load_rules()

    def test_no_rules_raises(self):
        # Directory exists but empty
        with self._patch_kompose_dir():
            with self.assertRaises(ValueError):
                load_rules()


class TestLintService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service_dir = Path(self.tmp.name) / "myservice"
        self.service_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_runs_all_rules(self):
        (self.service_dir / "compose.yml").write_text(
            "services:\n"
            "  app:\n"
            "    image: x\n"
        )
        rules = [
            RuleSpec(
                name="must-have-foo",
                category="cat",
                type="substring_required",
                params={"required": ["foo"]},
            ),
            RuleSpec(
                name="net",
                category="cat",
                handler="reverse_proxy_network",
            ),
        ]
        result = lint_service(self.service_dir, rules, {})
        self.assertEqual(len(result.rule_results), 2)
        self.assertEqual(result.error_count, 2)

    def test_missing_compose_yields_empty_result(self):
        rules = [RuleSpec(name="r", category="c", type="substring_required")]
        result = lint_service(self.service_dir, rules, {})
        self.assertEqual(result.rule_results, [])


class TestNoticesHook(unittest.TestCase):
    """Tests for the optional `notices()` hook on handlers."""

    def test_resolve_notices_returns_none_for_handler_without_notices(self):
        # reverse_proxy_network has no notices() function
        spec = RuleSpec(name="r", category="c", handler="reverse_proxy_network")
        self.assertIsNone(resolve_notices(spec))

    def test_resolve_notices_returns_callable_for_compose_includes_sync(self):
        spec = RuleSpec(name="r", category="c", handler="compose_includes_sync")
        fn = resolve_notices(spec)
        self.assertTrue(callable(fn))

    def test_resolve_notices_returns_none_for_builtin_type_without_hook(self):
        # substring_required has no `substring_required_notices` companion
        spec = RuleSpec(name="r", category="c", type="substring_required")
        self.assertIsNone(resolve_notices(spec))

    def test_run_notices_returns_empty_when_handler_has_none(self):
        spec = RuleSpec(name="r", category="c", handler="reverse_proxy_network")
        self.assertEqual(run_notices(spec, Path("/tmp"), []), [])

    def test_run_notices_invokes_when_handler_defines_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = Path(tmp)
            (host / "compose.yml").write_text("include:\n  - path: ghost/compose.yml\n")
            spec = RuleSpec(name="r", category="c", handler="compose_includes_sync")
            issues = run_notices(spec, host, [])
            self.assertEqual(len(issues), 1)


if __name__ == "__main__":
    unittest.main()
