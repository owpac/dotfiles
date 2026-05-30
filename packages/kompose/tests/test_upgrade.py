"""Tests for the upgrade command — image extraction, discovery, log parsing."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kompose import upgrade
from kompose.upgrade import (
    EXIT_OK,
    EXIT_PARTIAL,
    EXIT_TRIGGER_FAILED,
    LogEvent,
    TriggerResult,
    _extract_summary,
    _strip_env_quotes,
    discover_watchtower_url,
    extract_image_for_service,
    extract_images_from_compose,
    parse_watchtower_line,
    read_watchtower_token,
    render_event,
    resolve_target,
    slice_latest_session,
    trigger_update,
)


# ---------------------------------------------------------------------------
# Image extraction
# ---------------------------------------------------------------------------


class TestExtractImagesFromCompose(unittest.TestCase):
    def _write(self, content: str) -> Path:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".yml", mode="w")
        tmp.write(content)
        tmp.close()
        path = Path(tmp.name)
        self.addCleanup(path.unlink)
        return path

    def test_single_service_image(self):
        path = self._write("services:\n  paperless:\n    image: ghcr.io/paperless-ngx/paperless-ngx:latest\n")
        self.assertEqual(
            extract_images_from_compose(path),
            ["ghcr.io/paperless-ngx/paperless-ngx:latest"],
        )

    def test_multiple_services_unique_and_sorted(self):
        path = self._write(
            "services:\n"
            "  sonarr:\n    image: linuxserver/sonarr:latest\n"
            "  radarr:\n    image: linuxserver/radarr:latest\n"
            "  duplicate:\n    image: linuxserver/sonarr:latest\n"
        )
        self.assertEqual(
            extract_images_from_compose(path),
            ["linuxserver/radarr:latest", "linuxserver/sonarr:latest"],
        )

    def test_skips_build_only_service(self):
        path = self._write(
            "services:\n"
            "  app:\n    build: .\n"
            "  db:\n    image: postgres:16\n"
        )
        self.assertEqual(extract_images_from_compose(path), ["postgres:16"])

    def test_skips_digest_pinned(self):
        path = self._write(
            "services:\n"
            "  a:\n    image: foo/bar@sha256:abc\n"
            "  b:\n    image: foo/baz:1.2.3\n"
        )
        self.assertEqual(extract_images_from_compose(path), ["foo/baz:1.2.3"])

    def test_empty_or_missing_services(self):
        path = self._write("# no services key\n")
        self.assertEqual(extract_images_from_compose(path), [])

    def test_malformed_yaml_returns_empty(self):
        path = self._write("not: : valid: yaml: [")
        self.assertEqual(extract_images_from_compose(path), [])


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------


class TestResolveTarget(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.host_dir = Path(self._tmp.name) / "nas"
        self.host_dir.mkdir()

    def _make_service(self, name: str, compose: str) -> None:
        svc = self.host_dir / name
        svc.mkdir()
        (svc / "compose.yml").write_text(compose)

    def test_no_service_returns_full_update(self):
        with mock.patch.object(upgrade, "get_host_dir", return_value=self.host_dir):
            result = resolve_target(host="nas", service=None)
        self.assertIsNone(result.target)
        self.assertEqual(result.images, [])

    def test_group_expansion(self):
        self._make_service(
            "servarr",
            "services:\n  sonarr:\n    image: linuxserver/sonarr:latest\n  radarr:\n    image: linuxserver/radarr:latest\n",
        )
        with mock.patch.object(upgrade, "get_host_dir", return_value=self.host_dir):
            result = resolve_target(host="nas", service="servarr")
        self.assertEqual(result.target, "servarr")
        self.assertEqual(
            result.images,
            ["linuxserver/radarr:latest", "linuxserver/sonarr:latest"],
        )

    def test_missing_service_raises(self):
        with mock.patch.object(upgrade, "get_host_dir", return_value=self.host_dir), \
             mock.patch.object(upgrade, "build_service_to_group_map", return_value={}):
            with self.assertRaises(FileNotFoundError):
                resolve_target(host="nas", service="nope")

    def test_group_with_only_build_returns_empty_images(self):
        self._make_service("app", "services:\n  app:\n    build: .\n")
        with mock.patch.object(upgrade, "get_host_dir", return_value=self.host_dir):
            result = resolve_target(host="nas", service="app")
        self.assertEqual(result.images, [])

    def test_nested_docker_service_name(self):
        # `plex` is not a top-level dir but is declared inside the servarr group.
        self._make_service(
            "servarr",
            "services:\n"
            "  plex:\n    image: plexinc/pms-docker:latest\n"
            "  sonarr:\n    image: linuxserver/sonarr:latest\n",
        )
        with mock.patch.object(upgrade, "get_host_dir", return_value=self.host_dir), \
             mock.patch.object(upgrade, "build_service_to_group_map",
                               return_value={"plex": "servarr", "sonarr": "servarr"}):
            result = resolve_target(host="nas", service="plex")
        self.assertEqual(result.target, "plex")
        self.assertEqual(result.images, ["plexinc/pms-docker:latest"])

    def test_nested_service_with_build_only_returns_empty(self):
        self._make_service(
            "servarr",
            "services:\n  app:\n    build: .\n",
        )
        with mock.patch.object(upgrade, "get_host_dir", return_value=self.host_dir), \
             mock.patch.object(upgrade, "build_service_to_group_map",
                               return_value={"app": "servarr"}):
            result = resolve_target(host="nas", service="app")
        self.assertEqual(result.target, "app")
        self.assertEqual(result.images, [])


class TestExtractImageForService(unittest.TestCase):
    def _write(self, content: str) -> Path:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".yml", mode="w")
        tmp.write(content)
        tmp.close()
        path = Path(tmp.name)
        self.addCleanup(path.unlink)
        return path

    def test_returns_image(self):
        path = self._write("services:\n  plex:\n    image: plexinc/pms-docker:latest\n")
        self.assertEqual(extract_image_for_service(path, "plex"), "plexinc/pms-docker:latest")

    def test_returns_none_for_missing_service(self):
        path = self._write("services:\n  plex:\n    image: plexinc/pms-docker:latest\n")
        self.assertIsNone(extract_image_for_service(path, "sonarr"))

    def test_returns_none_for_build_only(self):
        path = self._write("services:\n  app:\n    build: .\n")
        self.assertIsNone(extract_image_for_service(path, "app"))

    def test_returns_none_for_digest_pinned(self):
        path = self._write("services:\n  app:\n    image: foo/bar@sha256:abc\n")
        self.assertIsNone(extract_image_for_service(path, "app"))


# ---------------------------------------------------------------------------
# Token reading
# ---------------------------------------------------------------------------


class TestStripEnvQuotes(unittest.TestCase):
    def test_strips_single_quotes(self):
        self.assertEqual(_strip_env_quotes("'abc'"), "abc")

    def test_strips_double_quotes(self):
        self.assertEqual(_strip_env_quotes('"abc"'), "abc")

    def test_leaves_unquoted_as_is(self):
        self.assertEqual(_strip_env_quotes("abc"), "abc")

    def test_handles_mismatched_quotes(self):
        self.assertEqual(_strip_env_quotes("'abc\""), "'abc\"")


class TestReadWatchtowerToken(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.host_dir = Path(self._tmp.name) / "nas"
        (self.host_dir / "watchtower").mkdir(parents=True)

    def test_reads_quoted_token(self):
        (self.host_dir / "watchtower" / ".env").write_text(
            "WATCHTOWER_HTTP_API_TOKEN='secret-token'\n"
        )
        with mock.patch.object(upgrade, "get_host_dir", return_value=self.host_dir):
            self.assertEqual(read_watchtower_token("nas"), "secret-token")

    def test_returns_none_when_env_missing(self):
        with mock.patch.object(upgrade, "get_host_dir", return_value=self.host_dir):
            self.assertIsNone(read_watchtower_token("nas"))

    def test_returns_none_when_token_empty(self):
        (self.host_dir / "watchtower" / ".env").write_text(
            "WATCHTOWER_HTTP_API_TOKEN=''\n"
        )
        with mock.patch.object(upgrade, "get_host_dir", return_value=self.host_dir):
            self.assertIsNone(read_watchtower_token("nas"))


# ---------------------------------------------------------------------------
# URL discovery
# ---------------------------------------------------------------------------


class TestDiscoverWatchtowerUrl(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.host_dir = Path(self._tmp.name) / "nas"
        (self.host_dir / "watchtower").mkdir(parents=True)

    def _write_compose(self, content: str) -> None:
        (self.host_dir / "watchtower" / "compose.yml").write_text(content)

    def test_config_override_wins(self):
        self._write_compose(
            "services:\n  watchtower:\n    networks:\n      reverse-proxy:\n"
            "        ipv4_address: 10.10.10.200\n"
        )
        with mock.patch.object(upgrade, "get_host_dir", return_value=self.host_dir), \
             mock.patch.object(upgrade, "load_kompose_config",
                               return_value={"watchtower": {"url": "http://override:9000/"}}):
            self.assertEqual(discover_watchtower_url("nas"), "http://override:9000")

    def test_derives_from_compose_ipv4(self):
        self._write_compose(
            "services:\n  watchtower:\n    networks:\n      reverse-proxy:\n"
            "        ipv4_address: 10.10.10.200\n"
        )
        with mock.patch.object(upgrade, "get_host_dir", return_value=self.host_dir), \
             mock.patch.object(upgrade, "load_kompose_config", return_value={}):
            self.assertEqual(discover_watchtower_url("nas"), "http://10.10.10.200:8080")

    def test_falls_back_to_first_network_with_ipv4(self):
        self._write_compose(
            "services:\n  watchtower:\n    networks:\n      other-net:\n"
            "        ipv4_address: 172.20.0.5\n"
        )
        with mock.patch.object(upgrade, "get_host_dir", return_value=self.host_dir), \
             mock.patch.object(upgrade, "load_kompose_config", return_value={}):
            self.assertEqual(discover_watchtower_url("nas"), "http://172.20.0.5:8080")

    def test_returns_none_when_no_ip(self):
        self._write_compose("services:\n  watchtower:\n    image: x\n")
        with mock.patch.object(upgrade, "get_host_dir", return_value=self.host_dir), \
             mock.patch.object(upgrade, "load_kompose_config", return_value={}):
            self.assertIsNone(discover_watchtower_url("nas"))

    def test_returns_none_when_compose_missing(self):
        with mock.patch.object(upgrade, "get_host_dir", return_value=self.host_dir), \
             mock.patch.object(upgrade, "load_kompose_config", return_value={}):
            self.assertIsNone(discover_watchtower_url("nas"))


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------


class TestParseWatchtowerLine(unittest.TestCase):
    def test_strips_ansi_and_extracts_message(self):
        line = "\x1b[36mINFO\x1b[0m[0214] Received HTTP API update request              \x1b[36mmethod\x1b[0m=POST \x1b[36mpath\x1b[0m=/v1/update"
        event = parse_watchtower_line(line)
        self.assertIsNotNone(event)
        self.assertEqual(event.level, "INFO")
        self.assertEqual(event.message, "Received HTTP API update request")
        self.assertEqual(event.fields, {"method": "POST", "path": "/v1/update"})

    def test_parses_session_completed(self):
        line = "INFO[0232] Update session completed                      failed=0 notify=no scanned=40 updated=0"
        event = parse_watchtower_line(line)
        self.assertEqual(event.message, "Update session completed")
        self.assertEqual(event.fields["failed"], "0")
        self.assertEqual(event.fields["scanned"], "40")
        self.assertEqual(event.fields["updated"], "0")

    def test_parses_quoted_values(self):
        line = 'DEBU[0214] Setting field msg="a=b with spaces" other=42'
        event = parse_watchtower_line(line)
        self.assertEqual(event.fields["msg"], "a=b with spaces")
        self.assertEqual(event.fields["other"], "42")

    def test_returns_none_for_blank(self):
        self.assertIsNone(parse_watchtower_line(""))

    def test_returns_none_for_unparseable(self):
        self.assertIsNone(parse_watchtower_line("random docker log line without level prefix"))


class TestSliceLatestSession(unittest.TestCase):
    def test_slices_between_trigger_and_completed(self):
        lines = [
            "INFO[0100] Watchtower starting",
            "INFO[0101] Update session completed                      failed=0 scanned=10 updated=0",
            "INFO[0200] Received HTTP API update request              method=POST path=/v1/update",
            "INFO[0201] Pulling new image                             image=foo/bar:latest",
            "INFO[0202] Stopping container                            container=foo",
            "INFO[0203] Update session completed                      failed=0 scanned=10 updated=1",
        ]
        events = slice_latest_session(lines)
        messages = [ev.message for ev in events]
        self.assertEqual(messages[0], "Received HTTP API update request")
        self.assertEqual(messages[-1], "Update session completed")
        self.assertEqual(len(events), 4)

    def test_in_progress_session_returns_up_to_eof(self):
        lines = [
            "INFO[0100] Received HTTP API update request              method=POST path=/v1/update",
            "INFO[0101] Pulling new image                             image=foo/bar:latest",
            # no Session completed yet
        ]
        events = slice_latest_session(lines)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[-1].message, "Pulling new image")

    def test_empty_logs(self):
        self.assertEqual(slice_latest_session([]), [])

    def test_no_recognized_markers_returns_everything(self):
        lines = [
            "INFO[0100] Some unrelated startup line",
            "INFO[0101] Another line",
        ]
        events = slice_latest_session(lines)
        self.assertEqual(len(events), 2)


# ---------------------------------------------------------------------------
# Event rendering
# ---------------------------------------------------------------------------


class TestRenderEvent(unittest.TestCase):
    def test_renders_pull(self):
        ev = LogEvent(level="INFO", message="Pulling new image", fields={"image": "foo/bar:latest"})
        out = render_event(ev)
        self.assertIn("pulling", out)
        self.assertIn("foo/bar:latest", out)

    def test_renders_session_completed_with_counts(self):
        ev = LogEvent(
            level="INFO",
            message="Update session completed",
            fields={"failed": "1", "scanned": "10", "updated": "3"},
        )
        out = render_event(ev)
        self.assertIn("3 updated", out)
        self.assertIn("1 failed", out)
        self.assertIn("session done", out)

    def test_skips_debug_lines(self):
        ev = LogEvent(level="DEBU", message="Categorizing container status", fields={})
        self.assertIsNone(render_event(ev))

    def test_surfaces_warnings(self):
        ev = LogEvent(level="WARN", message="Some warning text", fields={"container": "x"})
        out = render_event(ev)
        self.assertIn("Some warning text", out)


# ---------------------------------------------------------------------------
# Summary extraction
# ---------------------------------------------------------------------------


class TestExtractSummary(unittest.TestCase):
    def test_metric_block(self):
        body = {"metric": {"scanned": 10, "updated": 3, "failed": 1}}
        self.assertEqual(_extract_summary(body), (3, 1, 6))

    def test_inline_metrics(self):
        body = {"scanned": 5, "updated": 2, "failed": 0}
        self.assertEqual(_extract_summary(body), (2, 0, 3))

    def test_missing_returns_zeros(self):
        self.assertEqual(_extract_summary({}), (0, 0, 0))

    def test_none_returns_zeros(self):
        self.assertEqual(_extract_summary(None), (0, 0, 0))

    def test_skipped_never_negative(self):
        body = {"scanned": 1, "updated": 5, "failed": 0}
        _, _, skipped = _extract_summary(body)
        self.assertGreaterEqual(skipped, 0)


# ---------------------------------------------------------------------------
# HTTP trigger
# ---------------------------------------------------------------------------


class TestTriggerUpdate(unittest.TestCase):
    def _mock_urlopen(self, status=200, body=b'{"metric": {"scanned": 1, "updated": 1, "failed": 0}}'):
        resp = mock.MagicMock()
        resp.status = status
        resp.read.return_value = body
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        return resp

    def test_success_no_filter(self):
        with mock.patch("urllib.request.urlopen", return_value=self._mock_urlopen()) as op:
            result = trigger_update("http://wt:8080", "tok", [])
        called_with = op.call_args[0][0]
        self.assertTrue(called_with.full_url.endswith("/v1/update"))
        self.assertEqual(called_with.get_header("Authorization"), "Bearer tok")
        self.assertEqual(result.http_status, 200)
        self.assertEqual(result.body["metric"]["updated"], 1)

    def test_appends_image_query(self):
        with mock.patch("urllib.request.urlopen", return_value=self._mock_urlopen()) as op:
            trigger_update("http://wt:8080", "tok", ["foo/bar:latest", "baz/qux:1"])
        url = op.call_args[0][0].full_url
        self.assertIn("image=foo%2Fbar%3Alatest", url)
        self.assertIn("image=baz%2Fqux%3A1", url)

    def test_http_error_captured(self):
        import urllib.error
        err = urllib.error.HTTPError(
            url="http://wt:8080/v1/update", code=401, msg="Unauthorized",
            hdrs=None, fp=mock.MagicMock(read=lambda: b'{"error":"unauthorized"}'),
        )
        with mock.patch("urllib.request.urlopen", side_effect=err):
            result = trigger_update("http://wt:8080", "tok", [])
        self.assertEqual(result.http_status, 401)
        self.assertEqual(result.body, {"error": "unauthorized"})

    def test_network_error_captured(self):
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("dns")):
            result = trigger_update("http://wt:8080", "tok", [])
        self.assertEqual(result.http_status, 0)
        self.assertIn("dns", result.error)


# ---------------------------------------------------------------------------
# cmd_upgrade exit codes (HTTP mocked, tail no-op)
# ---------------------------------------------------------------------------


class TestCmdUpgradeExitCodes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.host_dir = Path(self._tmp.name) / "nas"
        (self.host_dir / "watchtower").mkdir(parents=True)
        (self.host_dir / "watchtower" / ".env").write_text(
            "WATCHTOWER_HTTP_API_TOKEN='tok'\n"
        )
        (self.host_dir / "watchtower" / "compose.yml").write_text(
            "services:\n  watchtower:\n    networks:\n      reverse-proxy:\n"
            "        ipv4_address: 10.10.10.200\n"
        )

    def _args(self, **kwargs) -> mock.MagicMock:
        ns = mock.MagicMock()
        ns.host = "nas"
        ns.service = kwargs.get("service")
        ns.force = kwargs.get("force", True)
        ns.logs = kwargs.get("logs", False)
        return ns

    def _patch_env(self):
        return mock.patch.multiple(
            upgrade,
            get_host_dir=mock.MagicMock(return_value=self.host_dir),
            load_kompose_config=mock.MagicMock(return_value={}),
        )

    def _patch_tail(self):
        # The live tail spawns docker logs; replace it with a no-op.
        return mock.patch.object(upgrade, "WatchtowerLogTail")

    def test_success_returns_zero(self):
        with self._patch_env(), self._patch_tail(), \
             mock.patch.object(upgrade, "trigger_update",
                               return_value=TriggerResult(200, {"metric": {"scanned": 5, "updated": 2, "failed": 0}})):
            self.assertEqual(upgrade.cmd_upgrade(self._args()), EXIT_OK)

    def test_partial_returns_one(self):
        with self._patch_env(), self._patch_tail(), \
             mock.patch.object(upgrade, "trigger_update",
                               return_value=TriggerResult(200, {"metric": {"scanned": 5, "updated": 1, "failed": 2}})):
            self.assertEqual(upgrade.cmd_upgrade(self._args()), EXIT_PARTIAL)

    def test_http_error_returns_two(self):
        with self._patch_env(), self._patch_tail(), \
             mock.patch.object(upgrade, "trigger_update",
                               return_value=TriggerResult(401, None, error="Unauthorized")):
            self.assertEqual(upgrade.cmd_upgrade(self._args()), EXIT_TRIGGER_FAILED)

    def test_missing_token_returns_two(self):
        (self.host_dir / "watchtower" / ".env").write_text("OTHER=1\n")
        with self._patch_env(), self._patch_tail():
            self.assertEqual(upgrade.cmd_upgrade(self._args()), EXIT_TRIGGER_FAILED)

    def test_targeted_no_updatable_images_returns_zero(self):
        (self.host_dir / "app").mkdir()
        (self.host_dir / "app" / "compose.yml").write_text(
            "services:\n  app:\n    build: .\n"
        )
        with self._patch_env(), self._patch_tail(), \
             mock.patch.object(upgrade, "trigger_update") as t:
            code = upgrade.cmd_upgrade(self._args(service="app"))
        self.assertEqual(code, EXIT_OK)
        t.assert_not_called()


if __name__ == "__main__":
    unittest.main()
