"""Tests for built-in rule types and Python handlers."""

import tempfile
import unittest
from pathlib import Path

from kompose._engine import LintContext
from kompose.rules._builtin import (
    property_order,
    substring_forbidden,
    substring_required,
)
from kompose.rules import (
    compose_includes_sync,
    reverse_proxy_network,
    traefik_middleware_correlation,
    traefik_router_naming,
)

FIXTURES = Path(__file__).parent / "fixtures"


def make_ctx(content: str, service_name: str = "test-service", globals_dict: dict | None = None) -> LintContext:
    return LintContext(
        service_name=service_name,
        compose_path=Path("/tmp/compose.yml"),
        content=content,
        parsed={},
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


if __name__ == "__main__":
    unittest.main()
