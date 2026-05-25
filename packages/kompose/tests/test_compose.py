"""Tests for compose module."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kompose import compose, config
from kompose.compose import (
    _parse_ports_string,
    build_compose_command,
    build_service_to_group_map,
    get_compose_files,
    get_root_compose,
    parse_compose_services,
    parse_ip_for_sort,
    resolve_root_targets,
)


class TestParseIpForSort(unittest.TestCase):
    def test_parse_valid_ip(self):
        self.assertEqual(parse_ip_for_sort("10.10.10.5"), (10, 10, 10, 5))

    def test_parse_ip_sorts_correctly(self):
        ips = ["10.10.10.20", "10.10.10.5", "10.10.10.100", "10.10.10.2"]
        self.assertEqual(
            sorted(ips, key=parse_ip_for_sort),
            ["10.10.10.2", "10.10.10.5", "10.10.10.20", "10.10.10.100"],
        )

    def test_parse_empty_ip(self):
        self.assertEqual(parse_ip_for_sort(""), (999, 999, 999, 999))

    def test_parse_none_ip(self):
        self.assertEqual(parse_ip_for_sort(None), (999, 999, 999, 999))

    def test_empty_ips_sort_last(self):
        ips = ["10.10.10.5", "", "10.10.10.2", ""]
        self.assertEqual(
            sorted(ips, key=parse_ip_for_sort),
            ["10.10.10.2", "10.10.10.5", "", ""],
        )


class TestBuildComposeCommand(unittest.TestCase):
    def test_build_basic_command(self):
        cmd = build_compose_command([Path("/path/to/compose.yml")], "up")
        self.assertEqual(cmd, ["docker", "compose", "-f", "/path/to/compose.yml", "up"])

    def test_build_command_multiple_files(self):
        cmd = build_compose_command([Path("/base/compose.yml"), Path("/host/compose.yml")], "up")
        self.assertEqual(cmd, [
            "docker", "compose",
            "-f", "/base/compose.yml",
            "-f", "/host/compose.yml",
            "up",
        ])

    def test_build_command_with_extra_args(self):
        cmd = build_compose_command([Path("/path/compose.yml")], "up", ["-d", "--build"])
        self.assertEqual(cmd, ["docker", "compose", "-f", "/path/compose.yml", "up", "-d", "--build"])

    def test_build_command_no_extra_args(self):
        cmd = build_compose_command([Path("/path/compose.yml")], "down", None)
        self.assertEqual(cmd, ["docker", "compose", "-f", "/path/compose.yml", "down"])

    def test_build_command_with_containers(self):
        cmd = build_compose_command([Path("/path/compose.yml")], "up", ["-d"], ["plex", "sonarr"])
        self.assertEqual(cmd, ["docker", "compose", "-f", "/path/compose.yml", "up", "-d", "plex", "sonarr"])

    def test_build_command_with_containers_no_extra_args(self):
        cmd = build_compose_command([Path("/path/compose.yml")], "down", None, ["plex"])
        self.assertEqual(cmd, ["docker", "compose", "-f", "/path/compose.yml", "down", "plex"])


class TestParsePortsString(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(_parse_ports_string(""), [])

    def test_single_port(self):
        self.assertEqual(
            _parse_ports_string("0.0.0.0:8080->80/tcp"),
            [{"PublishedPort": 8080, "TargetPort": 80}],
        )

    def test_dual_stack_deduplication(self):
        self.assertEqual(
            _parse_ports_string("0.0.0.0:8080->80/tcp, :::8080->80/tcp"),
            [{"PublishedPort": 8080, "TargetPort": 80}],
        )

    def test_multiple_ports(self):
        self.assertEqual(
            _parse_ports_string("0.0.0.0:8080->80/tcp, 0.0.0.0:8443->443/tcp"),
            [
                {"PublishedPort": 8080, "TargetPort": 80},
                {"PublishedPort": 8443, "TargetPort": 443},
            ],
        )

    def test_exposed_only_ignored(self):
        self.assertEqual(_parse_ports_string("80/tcp, 443/tcp"), [])

    def test_mixed_published_and_exposed(self):
        self.assertEqual(
            _parse_ports_string("80/tcp, 0.0.0.0:8080->80/tcp, 443/tcp"),
            [{"PublishedPort": 8080, "TargetPort": 80}],
        )


class _WorkspaceFixture(unittest.TestCase):
    """Common setUp for tests that patch WORKSPACE_DIR with a temp tree."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.host_dir = self.workspace / "nas"
        self.host_dir.mkdir()
        self._patch = mock.patch.object(config, "WORKSPACE_DIR", self.workspace)
        self._patch.start()
        self._patch2 = mock.patch.object(compose, "WORKSPACE_DIR", self.workspace)
        self._patch2.start()

    def tearDown(self):
        self._patch.stop()
        self._patch2.stop()
        self.tmp.cleanup()


class TestParseComposeServices(unittest.TestCase):
    def test_parses_services_keys(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            f.write("services:\n  sonarr:\n    image: x\n  radarr:\n    image: y\n")
            f.flush()
            services = parse_compose_services(Path(f.name))
        self.assertEqual(sorted(services), ["radarr", "sonarr"])

    def test_returns_empty_on_invalid_yaml(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            f.write("not: yaml: invalid: {[")
            f.flush()
            services = parse_compose_services(Path(f.name))
        self.assertEqual(services, [])

    def test_returns_empty_when_no_services_key(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            f.write("networks:\n  foo:\n    external: true\n")
            f.flush()
            services = parse_compose_services(Path(f.name))
        self.assertEqual(services, [])


class TestGetRootCompose(_WorkspaceFixture):
    def test_returns_none_when_missing(self):
        self.assertIsNone(get_root_compose("nas"))

    def test_returns_path_when_present(self):
        root = self.host_dir / "compose.yml"
        root.write_text("services: {}\n")
        self.assertEqual(get_root_compose("nas"), root)


class TestResolveRootTargets(_WorkspaceFixture):
    def setUp(self):
        super().setUp()
        # Create a "servarr" group with multiple services
        servarr = self.host_dir / "servarr"
        servarr.mkdir()
        (servarr / "compose.yml").write_text(
            "services:\n  sonarr:\n    image: x\n  radarr:\n    image: y\n  plex:\n    image: z\n"
        )

    def test_no_service_arg_returns_empty(self):
        self.assertEqual(resolve_root_targets("nas", None, None), [])

    def test_group_arg_expands(self):
        result = resolve_root_targets("nas", "servarr", None)
        self.assertEqual(sorted(result), ["plex", "radarr", "sonarr"])

    def test_group_arg_with_container_args_passes_through(self):
        result = resolve_root_targets("nas", "servarr", ["plex"])
        self.assertEqual(result, ["plex"])

    def test_non_group_arg_passes_through(self):
        # 'plex' isn't a directory, treat as a service name directly
        self.assertEqual(resolve_root_targets("nas", "plex", None), ["plex"])


class TestBuildServiceToGroupMap(_WorkspaceFixture):
    def test_no_root_returns_empty(self):
        self.assertEqual(build_service_to_group_map("nas"), {})

    def test_maps_services_to_their_group_dir(self):
        servarr = self.host_dir / "servarr"
        servarr.mkdir()
        (servarr / "compose.yml").write_text("services:\n  sonarr:\n    image: x\n  radarr:\n    image: y\n")
        paperless = self.host_dir / "paperless"
        paperless.mkdir()
        (paperless / "compose.yml").write_text("services:\n  paperless:\n    image: z\n")

        (self.host_dir / "compose.yml").write_text(
            "include:\n"
            "  - path: servarr/compose.yml\n"
            "  - path: paperless/compose.yml\n"
        )

        mapping = build_service_to_group_map("nas")
        self.assertEqual(
            mapping,
            {"sonarr": "servarr", "radarr": "servarr", "paperless": "paperless"},
        )

    def test_handles_short_form_include(self):
        servarr = self.host_dir / "servarr"
        servarr.mkdir()
        (servarr / "compose.yml").write_text("services:\n  sonarr:\n    image: x\n")
        # Short form: include is a list of strings rather than dicts
        (self.host_dir / "compose.yml").write_text(
            "include:\n  - servarr/compose.yml\n"
        )

        self.assertEqual(build_service_to_group_map("nas"), {"sonarr": "servarr"})

    def test_skips_includes_with_missing_files(self):
        (self.host_dir / "compose.yml").write_text(
            "include:\n  - path: ghost/compose.yml\n"
        )
        self.assertEqual(build_service_to_group_map("nas"), {})


class TestGetComposeFiles(_WorkspaceFixture):
    def test_legacy_host_only(self):
        host_compose = self.host_dir / "paperless" / "compose.yml"
        host_compose.parent.mkdir()
        host_compose.write_text("services: {}\n")
        self.assertEqual(get_compose_files("paperless", "nas"), [host_compose])

    def test_legacy_layered_base_and_host(self):
        base_compose = self.workspace / "base" / "paperless" / "compose.yml"
        base_compose.parent.mkdir(parents=True)
        base_compose.write_text("services: {}\n")
        host_compose = self.host_dir / "paperless" / "compose.yml"
        host_compose.parent.mkdir()
        host_compose.write_text("services: {}\n")
        self.assertEqual(get_compose_files("paperless", "nas"), [base_compose, host_compose])

    def test_returns_empty_when_nothing_found(self):
        self.assertEqual(get_compose_files("does-not-exist", "nas"), [])


if __name__ == "__main__":
    unittest.main()
