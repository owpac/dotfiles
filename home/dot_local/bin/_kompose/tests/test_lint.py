"""Tests for lint module."""

import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from _kompose.lint import (
    extract_compose_service_props,
    find_order_fixes,
    find_router_issues,
    find_middleware_issues,
    find_config_issues,
    COMPOSE_PROPERTY_ORDER,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestExtractComposeServiceProps(unittest.TestCase):
    def test_extract_props_valid(self):
        content = (FIXTURES / "compose_valid.yml").read_text()
        props = extract_compose_service_props(content)

        self.assertIn("app", props)
        prop_names = [p[0] for p in props["app"]]
        self.assertIn("container_name", prop_names)
        self.assertIn("image", prop_names)
        self.assertIn("logging", prop_names)

    def test_extract_props_multiple_services(self):
        content = (FIXTURES / "compose_router_issues.yml").read_text()
        props = extract_compose_service_props(content)

        self.assertIn("public-app", props)
        self.assertIn("private-wrong", props)


class TestFindOrderFixes(unittest.TestCase):
    def test_valid_order(self):
        content = (FIXTURES / "compose_valid.yml").read_text()
        props = extract_compose_service_props(content)
        issues = find_order_fixes(props["app"])

        self.assertEqual(len(issues), 0)

    def test_order_issues(self):
        content = (FIXTURES / "compose_order_issues.yml").read_text()
        props = extract_compose_service_props(content)
        issues = find_order_fixes(props["app"])

        # image before container_name, env_file after environment, user after volumes
        self.assertGreater(len(issues), 0)

        # Check that fixes mention the right properties
        fixes = [issue.fix for issue in issues]
        fix_text = " ".join(fixes)
        self.assertIn("container_name", fix_text)

    def test_property_order_is_alphabetical(self):
        # Verify COMPOSE_PROPERTY_ORDER is alphabetically sorted
        self.assertEqual(COMPOSE_PROPERTY_ORDER, sorted(COMPOSE_PROPERTY_ORDER))


class TestFindRouterIssues(unittest.TestCase):
    def test_valid_private_router(self):
        content = (FIXTURES / "compose_valid.yml").read_text()
        issues = find_router_issues(content)

        self.assertEqual(len(issues), 0)

    def test_public_without_suffix(self):
        content = (FIXTURES / "compose_router_issues.yml").read_text()
        issues = find_router_issues(content)

        # public-app has owpac.com but no -private/-public suffix
        issue_text = " ".join(issues)
        self.assertIn("public-app", issue_text)
        self.assertIn("missing -private/-public", issue_text)

    def test_private_with_public_suffix(self):
        # Private-only service with -public suffix should fail
        content = """
        labels:
          - "traefik.http.routers.myapp-public.rule=Host(`app.owpac.net`)"
        """
        issues = find_router_issues(content)

        self.assertEqual(len(issues), 1)
        self.assertIn("-private", issues[0])

    def test_private_without_suffix_is_ok(self):
        # Private-only service without suffix is fine
        content = """
        labels:
          - "traefik.http.routers.myapp.rule=Host(`app.owpac.net`)"
        """
        issues = find_router_issues(content)

        self.assertEqual(len(issues), 0)

    def test_exclusion(self):
        content = """
        labels:
          - "traefik.http.routers.excluded.rule=Host(`app.owpac.com`)"
        """
        issues = find_router_issues(content, exclude={"excluded"})

        self.assertEqual(len(issues), 0)

    def test_wildcard_certs_ignored(self):
        content = """
        labels:
          - "traefik.http.routers.wildcard-certs.rule=Host(`*.owpac.com`)"
        """
        issues = find_router_issues(content)

        self.assertEqual(len(issues), 0)


class TestFindMiddlewareIssues(unittest.TestCase):
    def test_valid_middleware(self):
        content = (FIXTURES / "compose_valid.yml").read_text()
        issues = find_middleware_issues(content)

        self.assertEqual(len(issues), 0)

    def test_public_with_lan_middleware(self):
        content = (FIXTURES / "compose_middleware_issues.yml").read_text()
        issues = find_middleware_issues(content)

        # app-public uses lan@file but is on owpac.com
        issue_text = " ".join(issues)
        self.assertIn("app-public", issue_text)
        self.assertIn("wan@file", issue_text)

    def test_private_with_wan_middleware(self):
        content = (FIXTURES / "compose_middleware_issues.yml").read_text()
        issues = find_middleware_issues(content)

        # app-private uses wan@file but is on owpac.net
        issue_text = " ".join(issues)
        self.assertIn("app-private", issue_text)
        self.assertIn("lan@file", issue_text)

    def test_exclusion(self):
        content = (FIXTURES / "compose_middleware_issues.yml").read_text()
        issues = find_middleware_issues(content, exclude={"app-public", "app-private"})

        self.assertEqual(len(issues), 0)


class TestFindConfigIssues(unittest.TestCase):
    def test_valid_config(self):
        content = (FIXTURES / "compose_valid.yml").read_text()
        issues = find_config_issues(content, "test-service")

        self.assertEqual(len(issues), 0)

    def test_missing_logging(self):
        content = """
        services:
          app:
            image: test
            networks:
              - reverse-proxy
        """
        issues = find_config_issues(content, "test-service")

        self.assertIn("missing logging", issues)

    def test_missing_network(self):
        content = """
        services:
          app:
            image: test
            logging:
              driver: local
        """
        issues = find_config_issues(content, "test-service")

        self.assertIn("missing network: reverse-proxy", issues)

    def test_network_mode_is_ok(self):
        # network_mode is an alternative to reverse-proxy
        content = """
        services:
          app:
            image: test
            network_mode: host
            logging:
              driver: local
        """
        issues = find_config_issues(content, "test-service")

        self.assertNotIn("missing network: reverse-proxy", issues)

    def test_logging_exclusion(self):
        content = "services:\n  app:\n    image: test"
        issues = find_config_issues(content, "excluded-service", exclude_logging={"excluded-service"})

        self.assertNotIn("missing logging", issues)

    def test_network_exclusion(self):
        content = """
        services:
          app:
            image: test
            logging:
              driver: local
        """
        issues = find_config_issues(content, "excluded-service", exclude_network={"excluded-service"})

        self.assertNotIn("missing network: reverse-proxy", issues)


if __name__ == "__main__":
    unittest.main()
