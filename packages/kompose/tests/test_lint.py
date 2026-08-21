"""Tests for built-in rule types and Python handlers."""

import tempfile
import unittest
from pathlib import Path

import yaml

from kompose._engine import LintContext
from kompose.rules._builtin import (
    property_order,
    property_order_fix,
    substring_forbidden,
    substring_required,
)
from kompose.rules import (
    compose_includes_sync,
    env_check,
    reverse_proxy_network,
    service_networks,
    traefik_middleware_correlation,
    traefik_router_naming,
)

FIXTURES = Path(__file__).parent / "fixtures"


def make_ctx(content: str, service_name: str = "test-service", globals_dict: dict | None = None) -> LintContext:
    # Parse like the engine does, so handlers reading ctx.parsed see the same
    # thing they would at runtime.
    try:
        parsed = yaml.safe_load(content) or {}
    except yaml.YAMLError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return LintContext(
        service_name=service_name,
        compose_path=Path("/tmp/compose.yml"),
        content=content,
        parsed=parsed,
        globals=globals_dict or {},
    )


class TestSubstringRequired(unittest.TestCase):
    def test_all_present(self):
        ctx = make_ctx("logging:\n  driver: local\n")
        issues = substring_required(ctx, {"required": ["logging:", "driver: local"]}, set())
        self.assertEqual(issues, [])

    def test_missing_one(self):
        ctx = make_ctx("logging:\n  driver: json-file\n")
        issues = substring_required(ctx, {"required": ["logging:", "driver: local"]}, set())
        self.assertEqual(len(issues), 1)
        self.assertIn("driver: local", issues[0].message)

    def test_string_param(self):
        ctx = make_ctx("")
        issues = substring_required(ctx, {"required": "needle"}, set())
        self.assertEqual(len(issues), 1)

    def test_service_excluded(self):
        ctx = make_ctx("", service_name="legacy")
        issues = substring_required(ctx, {"required": ["needle"]}, {"legacy"})
        self.assertEqual(issues, [])

    # --- per-service behaviour ---------------------------------------------

    TWO_SERVICES = (
        "services:\n"
        "  a:\n"
        "    image: x\n"
        "    logging:\n"
        "      driver: local\n"
        "  b:\n"
        "    image: y\n"
    )

    def test_reports_the_service_that_lacks_it(self):
        """The case a whole-file match cannot catch: only one service has it."""
        ctx = make_ctx(self.TWO_SERVICES)
        issues = substring_required(ctx, {"required": ["driver: local"]}, set())
        self.assertEqual(len(issues), 1)
        self.assertIn("b", issues[0].message)
        self.assertEqual(issues[0].location, "b")

    def test_every_service_compliant(self):
        content = self.TWO_SERVICES.replace(
            "  b:\n    image: y\n",
            "  b:\n    image: y\n    logging:\n      driver: local\n",
        )
        ctx = make_ctx(content)
        self.assertEqual(substring_required(ctx, {"required": ["driver: local"]}, set()), [])

    def test_one_issue_per_service_and_substring(self):
        ctx = make_ctx("services:\n  a:\n    image: x\n  b:\n    image: y\n")
        issues = substring_required(ctx, {"required": ["logging:", "driver: local"]}, set())
        self.assertEqual(len(issues), 4)

    def test_commented_service_is_not_checked(self):
        content = (
            "services:\n"
            "  a:\n"
            "    image: x\n"
            "    logging:\n"
            "      driver: local\n"
            "  # b:\n"
            "  #   image: y\n"
        )
        ctx = make_ctx(content)
        self.assertEqual(substring_required(ctx, {"required": ["driver: local"]}, set()), [])

    def test_top_level_key_ends_the_services_block(self):
        """A networks: section must not be mistaken for a service."""
        content = self.TWO_SERVICES + "\nnetworks:\n  reverse-proxy:\n    external: true\n"
        ctx = make_ctx(content)
        issues = substring_required(ctx, {"required": ["driver: local"]}, set())
        self.assertEqual([i.location for i in issues], ["b"])

    def test_falls_back_to_whole_file_without_services(self):
        ctx = make_ctx("logging:\n  driver: local\n")
        self.assertEqual(substring_required(ctx, {"required": ["driver: local"]}, set()), [])


class TestSubstringForbidden(unittest.TestCase):
    def test_no_forbidden(self):
        ctx = make_ctx("image: myapp:1.2.3\n")
        issues = substring_forbidden(ctx, {"forbidden": [":latest"]}, set())
        self.assertEqual(issues, [])

    def test_with_forbidden(self):
        ctx = make_ctx("image: myapp:latest\n")
        issues = substring_forbidden(ctx, {"forbidden": [":latest"]}, set())
        self.assertEqual(len(issues), 1)

    def test_service_excluded(self):
        ctx = make_ctx("image: myapp:latest\n", service_name="legacy")
        issues = substring_forbidden(ctx, {"forbidden": [":latest"]}, {"legacy"})
        self.assertEqual(issues, [])


COMPOSE_ORDER = [
    "container_name", "depends_on", "env_file", "environment", "healthcheck",
    "image", "labels", "logging", "networks", "ports", "restart", "user", "volumes",
]


class TestPropertyOrder(unittest.TestCase):
    def test_valid_order(self):
        content = (FIXTURES / "compose_valid.yml").read_text()
        ctx = make_ctx(content)
        issues = property_order(ctx, {"order": COMPOSE_ORDER}, set())
        self.assertEqual(issues, [])

    def test_order_issues(self):
        content = (FIXTURES / "compose_order_issues.yml").read_text()
        ctx = make_ctx(content)
        issues = property_order(ctx, {"order": COMPOSE_ORDER}, set())
        self.assertGreater(len(issues), 0)
        fixes = " ".join(i.fix for i in issues)
        self.assertIn("container_name", fixes)

    def test_no_order_param(self):
        ctx = make_ctx("services:\n  app:\n    image: x\n")
        self.assertEqual(property_order(ctx, {}, set()), [])

    def test_multi_container_no_issues(self):
        content = (FIXTURES / "compose_router_issues.yml").read_text()
        ctx = make_ctx(content)
        issues = property_order(ctx, {"order": COMPOSE_ORDER}, set())
        self.assertEqual(issues, [])

    def test_warn_on_unknown_enabled_by_default(self):
        content = (
            "services:\n"
            "  app:\n"
            "    build:\n"
            "      context: .\n"
            "    container_name: app\n"
            "    image: x\n"
        )
        ctx = make_ctx(content)
        issues = property_order(ctx, {"order": ["container_name", "image"]}, set())
        # `build` is unknown → 1 warning. Known props are in correct order → no order issue.
        self.assertEqual(len(issues), 1)
        self.assertIn("unknown property `build`", issues[0].message)

    def test_warn_on_unknown_disabled(self):
        content = (
            "services:\n"
            "  app:\n"
            "    build:\n"
            "      context: .\n"
            "    container_name: app\n"
            "    image: x\n"
        )
        ctx = make_ctx(content)
        issues = property_order(
            ctx, {"order": ["container_name", "image"], "warn_on_unknown": False}, set()
        )
        self.assertEqual(issues, [])

    def test_warn_on_unknown_combines_with_order_issues(self):
        content = (
            "services:\n"
            "  app:\n"
            "    image: x\n"           # known, out of order
            "    build:\n"             # unknown
            "      context: .\n"
            "    container_name: app\n"  # known, out of order
        )
        ctx = make_ctx(content)
        issues = property_order(ctx, {"order": ["container_name", "image"]}, set())
        # 1 order issue (container_name should be before image) + 1 unknown warning (build)
        self.assertEqual(len(issues), 2)
        messages = " ".join(i.message for i in issues)
        self.assertIn("move `container_name`", messages)
        self.assertIn("unknown property `build`", messages)


class TestTraefikRouterNaming(unittest.TestCase):
    def test_valid(self):
        content = (FIXTURES / "compose_valid.yml").read_text()
        ctx = make_ctx(content)
        issues = traefik_router_naming.check(ctx, {}, set())
        self.assertEqual(issues, [])

    def test_public_without_suffix(self):
        content = (FIXTURES / "compose_router_issues.yml").read_text()
        ctx = make_ctx(content)
        issues = traefik_router_naming.check(ctx, {}, set())
        text = " ".join(i.message for i in issues)
        self.assertIn("public-app", text)

    def test_private_with_public_suffix(self):
        content = 'labels:\n  - "traefik.http.routers.myapp-public.rule=Host(`app.owpac.net`)"\n'
        ctx = make_ctx(content)
        issues = traefik_router_naming.check(ctx, {}, set())
        self.assertEqual(len(issues), 1)
        self.assertIn("private", issues[0].message)

    def test_private_without_suffix_ok(self):
        content = 'labels:\n  - "traefik.http.routers.myapp.rule=Host(`app.owpac.net`)"\n'
        ctx = make_ctx(content)
        issues = traefik_router_naming.check(ctx, {}, set())
        self.assertEqual(issues, [])

    def test_exclusion(self):
        content = 'labels:\n  - "traefik.http.routers.excluded.rule=Host(`app.owpac.com`)"\n'
        ctx = make_ctx(content)
        issues = traefik_router_naming.check(ctx, {}, {"excluded"})
        self.assertEqual(issues, [])

    def test_wildcard_certs_ignored(self):
        content = 'labels:\n  - "traefik.http.routers.wildcard-certs.rule=Host(`*.owpac.com`)"\n'
        ctx = make_ctx(content)
        issues = traefik_router_naming.check(ctx, {}, set())
        self.assertEqual(issues, [])

    def test_globals_override_domain(self):
        content = 'labels:\n  - "traefik.http.routers.r1.rule=Host(`app.example.com`)"\n'
        ctx = make_ctx(content, globals_dict={"public_domain": "example.com"})
        issues = traefik_router_naming.check(ctx, {}, set())
        self.assertEqual(len(issues), 1)


class TestTraefikMiddlewareCorrelation(unittest.TestCase):
    def test_valid(self):
        content = (FIXTURES / "compose_valid.yml").read_text()
        ctx = make_ctx(content)
        issues = traefik_middleware_correlation.check(ctx, {}, set())
        self.assertEqual(issues, [])

    def test_public_with_lan(self):
        content = (FIXTURES / "compose_middleware_issues.yml").read_text()
        ctx = make_ctx(content)
        issues = traefik_middleware_correlation.check(ctx, {}, set())
        text = " ".join(i.message for i in issues)
        self.assertIn("app-public", text)
        self.assertIn("wan@file", text)

    def test_private_with_wan(self):
        content = (FIXTURES / "compose_middleware_issues.yml").read_text()
        ctx = make_ctx(content)
        issues = traefik_middleware_correlation.check(ctx, {}, set())
        text = " ".join(i.message for i in issues)
        self.assertIn("app-private", text)
        self.assertIn("lan@file", text)

    def test_exclusion(self):
        content = (FIXTURES / "compose_middleware_issues.yml").read_text()
        ctx = make_ctx(content)
        issues = traefik_middleware_correlation.check(ctx, {}, {"app-public", "app-private"})
        self.assertEqual(issues, [])

    def test_globals_override_middleware(self):
        content = (
            'labels:\n'
            '  - "traefik.http.routers.r1.rule=Host(`a.owpac.com`)"\n'
            '  - "traefik.http.routers.r1.middlewares=custom-wan@file"\n'
        )
        ctx = make_ctx(content, globals_dict={"public_middleware": "custom-wan@file"})
        issues = traefik_middleware_correlation.check(ctx, {}, set())
        self.assertEqual(issues, [])


class TestReverseProxyNetwork(unittest.TestCase):
    def test_reverse_proxy_present(self):
        ctx = make_ctx("networks:\n  - reverse-proxy\n")
        issues = reverse_proxy_network.check(ctx, {}, set())
        self.assertEqual(issues, [])

    def test_network_mode_present(self):
        ctx = make_ctx("network_mode: host\n")
        issues = reverse_proxy_network.check(ctx, {}, set())
        self.assertEqual(issues, [])

    def test_neither(self):
        ctx = make_ctx("image: x\n")
        issues = reverse_proxy_network.check(ctx, {}, set())
        self.assertEqual(len(issues), 1)

    def test_service_excluded(self):
        ctx = make_ctx("image: x\n", service_name="legacy")
        issues = reverse_proxy_network.check(ctx, {}, {"legacy"})
        self.assertEqual(issues, [])

    def test_globals_override_network(self):
        ctx = make_ctx(
            "networks:\n  - my-proxy\n",
            globals_dict={"proxy_network": "my-proxy"},
        )
        issues = reverse_proxy_network.check(ctx, {}, set())
        self.assertEqual(issues, [])


class TestServiceNetworks(unittest.TestCase):
    """Tests for the service_networks handler."""

    COMPOSE = """\
services:
  web:
    image: nginx
    networks:
      network-tools:
        ipv4_address: 10.10.40.10
  worker:
    image: busybox
    networks:
      - network-media
      - byparr
  host_agent:
    image: busybox
    network_mode: host
"""

    def _check(self, params, exclude=frozenset()):
        return service_networks.check(make_ctx(self.COMPOSE), params, set(exclude))

    # network -> services, the same shape as the zone table it mirrors
    FULL_MAP = {
        "network-tools": ["web"],
        "network-media": ["worker"],
        "byparr": ["worker"],
    }

    def test_mapping_form_matches(self):
        self.assertEqual(self._check({"networks": self.FULL_MAP}), [])

    def test_service_on_several_networks(self):
        # worker appears under two networks and must hold exactly those
        issues = self._check({"networks": self.FULL_MAP})
        self.assertEqual([i for i in issues if "worker" in i.message], [])

    def test_missing_network_reported(self):
        m = dict(self.FULL_MAP, **{"socket-proxy": ["worker"]})
        issues = self._check({"networks": m})
        self.assertEqual(len(issues), 1)
        self.assertIn("missing socket-proxy", issues[0].message)

    def test_unexpected_network_reported(self):
        m = {k: v for k, v in self.FULL_MAP.items() if k != "byparr"}
        issues = self._check({"networks": m})
        self.assertEqual(len(issues), 1)
        self.assertIn("unexpected byparr", issues[0].message)

    def test_network_mode_service_skipped(self):
        names = " ".join(i.message for i in self._check({"networks": {}}))
        self.assertNotIn("host_agent", names)

    def test_service_in_no_network_is_an_error(self):
        issues = self._check({"networks": {}})
        self.assertEqual(len(issues), 2)
        self.assertTrue(all("listed in no network" in i.message for i in issues))

    def test_partial_map_still_flags_the_rest(self):
        issues = self._check({"networks": {"network-tools": ["web"]}})
        self.assertEqual(len(issues), 1)
        self.assertIn("worker", issues[0].message)

    def test_service_excluded(self):
        issues = self._check({"networks": {}}, exclude={"web", "worker"})
        self.assertEqual(issues, [])

    def test_service_without_networks_reports_missing(self):
        ctx = make_ctx("services:\n  bare:\n    image: x\n")
        issues = service_networks.check(ctx, {"networks": {"bare": ["network-main"]}}, set())
        self.assertEqual(len(issues), 1)
        self.assertIn("missing network-main", issues[0].message)


class TestComposeIncludesSync(unittest.TestCase):
    """Tests for the compose_includes_sync handler (check + notices)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.host_dir = Path(self.tmp.name)
        # Create two service dirs
        (self.host_dir / "paperless").mkdir()
        (self.host_dir / "paperless" / "compose.yml").write_text(
            "services:\n  paperless:\n    image: x\n"
        )
        (self.host_dir / "minecraft").mkdir()
        (self.host_dir / "minecraft" / "compose.yml").write_text(
            "services:\n  minecraft:\n    image: y\n"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _ctx(self, service_name: str) -> LintContext:
        return LintContext(
            service_name=service_name,
            compose_path=self.host_dir / service_name / "compose.yml",
            content="",
            parsed={},
            globals={},
        )

    def _write_root(self, body: str) -> None:
        (self.host_dir / "compose.yml").write_text(body)

    def test_check_passes_when_service_in_includes(self):
        self._write_root("include:\n  - path: paperless/compose.yml\n  - path: minecraft/compose.yml\n")
        issues = compose_includes_sync.check(self._ctx("paperless"), {}, set())
        self.assertEqual(issues, [])

    def test_check_flags_service_missing_from_includes(self):
        self._write_root("include:\n  - path: paperless/compose.yml\n")
        issues = compose_includes_sync.check(self._ctx("minecraft"), {}, set())
        self.assertEqual(len(issues), 1)
        self.assertIn("not in root compose include", issues[0].message)

    def test_check_respects_exclude(self):
        self._write_root("include:\n  - path: paperless/compose.yml\n")
        issues = compose_includes_sync.check(self._ctx("minecraft"), {}, {"minecraft"})
        self.assertEqual(issues, [])

    def test_check_skips_when_root_absent(self):
        # No root compose written
        issues = compose_includes_sync.check(self._ctx("paperless"), {}, set())
        self.assertEqual(issues, [])

    def test_notices_flags_orphan_include(self):
        self._write_root(
            "include:\n"
            "  - path: paperless/compose.yml\n"
            "  - path: ghost/compose.yml\n"   # dir doesn't exist
        )
        issues = compose_includes_sync.notices(self.host_dir, [], {}, set())
        self.assertEqual(len(issues), 1)
        self.assertIn("ghost/compose.yml", issues[0].message)

    def test_notices_respects_exclude(self):
        self._write_root("include:\n  - path: ghost/compose.yml\n")
        issues = compose_includes_sync.notices(self.host_dir, [], {}, {"ghost"})
        self.assertEqual(issues, [])

    def test_notices_handles_short_form_include(self):
        self._write_root("include:\n  - ghost/compose.yml\n")
        issues = compose_includes_sync.notices(self.host_dir, [], {}, set())
        self.assertEqual(len(issues), 1)

    def test_notices_skips_when_root_absent(self):
        self.assertEqual(compose_includes_sync.notices(self.host_dir, [], {}, set()), [])

    def test_custom_root_param(self):
        # Use a non-default root path
        (self.host_dir / "main.yml").write_text("include:\n  - path: paperless/compose.yml\n")
        issues = compose_includes_sync.check(
            self._ctx("paperless"), {"root": "main.yml"}, set()
        )
        self.assertEqual(issues, [])


class TestEnvCheck(unittest.TestCase):
    """Tests for the env_check handler."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service_dir = Path(self.tmp.name) / "paperless"
        self.service_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _ctx(self, service_name: str | None = None) -> LintContext:
        return LintContext(
            service_name=service_name or self.service_dir.name,
            compose_path=self.service_dir / "compose.yml",
            content="",
            parsed={},
            globals={},
        )

    def _write(self, name: str, body: str) -> None:
        (self.service_dir / name).write_text(body)

    def test_no_example_skipped(self):
        # No .env.example → silent skip
        self.assertEqual(env_check.check(self._ctx(), {}, set()), [])

    def test_in_sync_no_issues(self):
        self._write(".env", "FOO=bar\nBAZ=qux\n")
        self._write(".env.example", "FOO=''\nBAZ=''\n")
        self.assertEqual(env_check.check(self._ctx(), {}, set()), [])

    def test_missing_env_yields_one_issue_per_var(self):
        self._write(".env.example", "FOO=''\nBAR=''\nBAZ=''\n")
        # Note: no .env file
        issues = env_check.check(self._ctx(), {}, set())
        self.assertEqual(len(issues), 3)
        for issue in issues:
            self.assertIn(".env file not found", issue.message)
        var_names = {i.message for i in issues}
        # Each var named
        self.assertTrue(any("FOO" in m for m in var_names))
        self.assertTrue(any("BAR" in m for m in var_names))
        self.assertTrue(any("BAZ" in m for m in var_names))

    def test_drift_only_in_env(self):
        self._write(".env", "FOO=bar\nEXTRA=value\n")
        self._write(".env.example", "FOO=''\n")
        issues = env_check.check(self._ctx(), {}, set())
        # `EXTRA` is extra in .env, structure may also drift → at least 1 issue
        msgs = " ".join(i.message for i in issues)
        self.assertIn("EXTRA", msgs)
        self.assertIn("extra", msgs.lower())

    def test_drift_only_in_example(self):
        self._write(".env", "FOO=bar\n")
        self._write(".env.example", "FOO=''\nMISSING=''\n")
        issues = env_check.check(self._ctx(), {}, set())
        msgs = " ".join(i.message for i in issues)
        self.assertIn("MISSING", msgs)
        self.assertIn("missing", msgs.lower())

    def test_structure_drift_only(self):
        # Same vars, but .env has comments/blanks not reflected in .env.example
        self._write(".env", "# Section\nFOO=bar\n\nBAZ=qux\n")
        self._write(".env.example", "FOO=''\nBAZ=''\n")
        issues = env_check.check(self._ctx(), {}, set())
        self.assertEqual(len(issues), 1)
        self.assertIn("structure drift", issues[0].message)

    def test_service_excluded(self):
        self._write(".env.example", "FOO=''\n")
        # .env missing — would normally yield 1 issue, but excluded
        issues = env_check.check(self._ctx(), {}, {self.service_dir.name})
        self.assertEqual(issues, [])


class TestPropertyOrderFix(unittest.TestCase):
    """Tests for the property_order auto-fix (text-based reordering)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.compose = Path(self.tmp.name) / "paperless" / "compose.yml"
        self.compose.parent.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _ctx(self, content: str) -> LintContext:
        self.compose.write_text(content)
        return LintContext(
            service_name="paperless",
            compose_path=self.compose,
            content=content,
            parsed={},
            globals={},
        )

    def test_no_changes_when_already_ordered(self):
        content = (
            "services:\n"
            "  app:\n"
            "    container_name: app\n"
            "    image: x\n"
        )
        ctx = self._ctx(content)
        fixes = property_order_fix(ctx, {"order": ["container_name", "image"]}, set())
        self.assertEqual(fixes, [])
        self.assertEqual(self.compose.read_text(), content)

    def test_reorders_properties(self):
        content = (
            "services:\n"
            "  app:\n"
            "    image: foo:latest\n"
            "    container_name: app\n"
        )
        ctx = self._ctx(content)
        fixes = property_order_fix(ctx, {"order": ["container_name", "image"]}, set())
        self.assertEqual(len(fixes), 1)
        self.assertIn("app", fixes[0].message)
        new = self.compose.read_text()
        # container_name should appear before image now
        self.assertLess(new.index("container_name"), new.index("image"))

    def test_dry_run_does_not_write(self):
        content = (
            "services:\n"
            "  app:\n"
            "    image: x\n"
            "    container_name: app\n"
        )
        ctx = self._ctx(content)
        fixes = property_order_fix(ctx, {"order": ["container_name", "image"]}, set(), dry_run=True)
        self.assertEqual(len(fixes), 1)
        self.assertEqual(self.compose.read_text(), content)  # unchanged

    def test_preserves_value_blocks_with_lists(self):
        content = (
            "services:\n"
            "  app:\n"
            "    image: foo:latest\n"
            "    environment:\n"
            "      - TZ=Europe/Paris\n"
            "      - PUID=1000\n"
            "    container_name: app\n"
        )
        ctx = self._ctx(content)
        property_order_fix(ctx, {"order": ["container_name", "environment", "image"]}, set())
        new = self.compose.read_text()
        # Environment list items must stay attached to environment:
        env_idx = new.index("environment:")
        tz_idx = new.index("TZ=Europe/Paris")
        puid_idx = new.index("PUID=1000")
        self.assertLess(env_idx, tz_idx)
        self.assertLess(tz_idx, puid_idx)

    def test_comments_above_property_move_with_it(self):
        content = (
            "services:\n"
            "  app:\n"
            "    image: foo\n"
            "    # the next prop is container_name\n"
            "    container_name: app\n"
        )
        ctx = self._ctx(content)
        property_order_fix(ctx, {"order": ["container_name", "image"]}, set())
        new = self.compose.read_text()
        # The comment should now precede container_name AND container_name should be first
        lines = new.split("\n")
        cname_idx = next(i for i, l in enumerate(lines) if "container_name:" in l)
        cmt_idx = next(i for i, l in enumerate(lines) if "the next prop" in l)
        self.assertEqual(cmt_idx, cname_idx - 1)

    def test_excluded_container_not_touched(self):
        content = (
            "services:\n"
            "  app:\n"
            "    image: x\n"
            "    container_name: app\n"
        )
        ctx = self._ctx(content)
        fixes = property_order_fix(ctx, {"order": ["container_name", "image"]}, {"app"})
        self.assertEqual(fixes, [])

    def test_unknown_props_in_middle_are_not_touched(self):
        # When `check` says OK (all known props in correct order, unknown props
        # interleaved), `fix` must also say OK — same definition of "wrong order".
        content = (
            "services:\n"
            "  app:\n"
            "    build:\n"
            "      context: .\n"
            "    container_name: app\n"
            "    image: x\n"
        )
        ctx = self._ctx(content)
        # `build` is NOT in expected_order; container_name and image ARE and are in correct order.
        fixes = property_order_fix(ctx, {"order": ["container_name", "image"]}, set())
        self.assertEqual(fixes, [])
        self.assertEqual(self.compose.read_text(), content)  # untouched

    def test_unknown_props_keep_their_position_when_known_reorder(self):
        # If known props ARE out of order, only they swap — unknowns stay put.
        content = (
            "services:\n"
            "  app:\n"
            "    image: x\n"
            "    build:\n"
            "      context: .\n"
            "    container_name: app\n"
        )
        ctx = self._ctx(content)
        fixes = property_order_fix(ctx, {"order": ["container_name", "image"]}, set())
        self.assertEqual(len(fixes), 1)
        new = self.compose.read_text()
        # build: must remain between the two known props (position-wise)
        # Expected layout: container_name (was image's slot), build (unchanged), image (was container_name's slot)
        lines = new.split("\n")
        cname_idx = next(i for i, l in enumerate(lines) if l.strip().startswith("container_name"))
        build_idx = next(i for i, l in enumerate(lines) if l.strip().startswith("build:"))
        image_idx = next(i for i, l in enumerate(lines) if l.strip().startswith("image:"))
        self.assertLess(cname_idx, build_idx)
        self.assertLess(build_idx, image_idx)

    def test_multi_container_only_changed_ones_reported(self):
        content = (
            "services:\n"
            "  app1:\n"
            "    image: a\n"
            "    container_name: a\n"
            "  app2:\n"
            "    container_name: b\n"
            "    image: b\n"
        )
        ctx = self._ctx(content)
        fixes = property_order_fix(ctx, {"order": ["container_name", "image"]}, set())
        # only app1 needed reordering
        self.assertEqual(len(fixes), 1)
        self.assertIn("app1", fixes[0].message)
        self.assertNotIn("app2", fixes[0].message)


class TestComposeIncludesSyncFix(unittest.TestCase):
    """Tests for the compose_includes_sync auto-fix (add missing include entry)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.host_dir = Path(self.tmp.name)
        (self.host_dir / "paperless").mkdir()
        (self.host_dir / "paperless" / "compose.yml").write_text("services:\n  paperless:\n    image: x\n")
        (self.host_dir / "minecraft").mkdir()
        (self.host_dir / "minecraft" / "compose.yml").write_text("services:\n  minecraft:\n    image: y\n")

    def tearDown(self):
        self.tmp.cleanup()

    def _ctx(self, service_name: str) -> LintContext:
        return LintContext(
            service_name=service_name,
            compose_path=self.host_dir / service_name / "compose.yml",
            content="",
            parsed={},
            globals={},
        )

    def test_no_root_compose_returns_empty(self):
        # no root compose.yml at all
        fixes = compose_includes_sync.fix(self._ctx("minecraft"), {}, set())
        self.assertEqual(fixes, [])

    def test_already_included_no_op(self):
        (self.host_dir / "compose.yml").write_text(
            "include:\n  - path: paperless/compose.yml\n"
        )
        fixes = compose_includes_sync.fix(self._ctx("paperless"), {}, set())
        self.assertEqual(fixes, [])

    def test_excluded_not_added(self):
        (self.host_dir / "compose.yml").write_text("include:\n  - path: paperless/compose.yml\n")
        fixes = compose_includes_sync.fix(self._ctx("minecraft"), {}, {"minecraft"})
        self.assertEqual(fixes, [])

    def test_adds_missing_include_dict_form(self):
        (self.host_dir / "compose.yml").write_text(
            "include:\n  - path: paperless/compose.yml\n"
        )
        fixes = compose_includes_sync.fix(self._ctx("minecraft"), {}, set())
        self.assertEqual(len(fixes), 1)
        new_root = (self.host_dir / "compose.yml").read_text()
        self.assertIn("minecraft/compose.yml", new_root)
        # Should be in dict form (matches existing style)
        self.assertIn("- path: minecraft/compose.yml", new_root)

    def test_adds_missing_include_short_form(self):
        (self.host_dir / "compose.yml").write_text(
            "include:\n  - paperless/compose.yml\n"
        )
        fixes = compose_includes_sync.fix(self._ctx("minecraft"), {}, set())
        self.assertEqual(len(fixes), 1)
        new_root = (self.host_dir / "compose.yml").read_text()
        # Should match the short-form style
        self.assertIn("- minecraft/compose.yml", new_root)
        self.assertNotIn("path: minecraft", new_root)

    def test_dry_run_does_not_write(self):
        original = "include:\n  - path: paperless/compose.yml\n"
        (self.host_dir / "compose.yml").write_text(original)
        fixes = compose_includes_sync.fix(self._ctx("minecraft"), {}, set(), dry_run=True)
        self.assertEqual(len(fixes), 1)
        self.assertEqual((self.host_dir / "compose.yml").read_text(), original)


if __name__ == "__main__":
    unittest.main()
