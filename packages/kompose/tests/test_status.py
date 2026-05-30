"""Tests for status module — formatters and IP sort.

The status command itself (`cmd_status` / `_watch_status`) is exercised
end-to-end on the NAS; this file covers the pure formatters and helpers
that have no docker dependency.
"""

import re
import unittest

from kompose.status import (
    _format_cpu,
    _format_ports,
    _parse_exposed_ports,
    parse_ip_for_sort,
)


_ANSI = re.compile(r"\x1B\[[0-9;]*m")


def _strip(s: str) -> str:
    return _ANSI.sub("", s)


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


class TestParseExposedPorts(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(_parse_exposed_ports(""), [])

    def test_exposed_only_simple(self):
        self.assertEqual(_parse_exposed_ports("2283/tcp"), ["2283/tcp"])

    def test_published_returns_target(self):
        # Published entry → keep the right side (target inside the container)
        self.assertEqual(_parse_exposed_ports("0.0.0.0:8080->80/tcp"), ["80/tcp"])

    def test_dual_stack_deduplication(self):
        # IPv4 + IPv6 published forms of the same target collapse
        self.assertEqual(
            _parse_exposed_ports("0.0.0.0:8080->80/tcp, :::8080->80/tcp"),
            ["80/tcp"],
        )

    def test_mix_exposed_and_published(self):
        # AdGuard-style: a long list of bare exposed ports
        ports = _parse_exposed_ports("53/udp, 53/tcp, 80/tcp, 443/tcp")
        self.assertEqual(ports, ["53/udp", "53/tcp", "80/tcp", "443/tcp"])

    def test_port_range_preserved(self):
        ports = _parse_exposed_ports("8324/tcp, 32412-32414/udp, 32400/tcp")
        self.assertIn("32412-32414/udp", ports)

    def test_published_and_exposed_dedup(self):
        # Plex-style: exposed line + published line for the same port
        ports = _parse_exposed_ports("32400/tcp, 0.0.0.0:32400->32400/tcp")
        self.assertEqual(ports, ["32400/tcp"])


class TestFormatPorts(unittest.TestCase):
    def test_empty_renders_dash(self):
        self.assertEqual(_strip(_format_ports([])), "-")

    def test_under_limit(self):
        s = _format_ports(["80/tcp", "443/tcp"], limit=4)
        self.assertIn("80/tcp", s)
        self.assertIn("443/tcp", s)
        self.assertNotIn("+", s)

    def test_over_limit_appends_plus_n(self):
        ports = ["1/tcp", "2/tcp", "3/tcp", "4/tcp", "5/tcp", "6/tcp"]
        s = _format_ports(ports, limit=4)
        self.assertIn("+2", s)
        self.assertNotIn("5/tcp", s)


class TestFormatCpu(unittest.TestCase):
    def test_low_cpu(self):
        self.assertIn("0.1%", _strip(_format_cpu("0.05%")))

    def test_medium_cpu(self):
        # 60% should land in yellow band, but we just check the number
        self.assertIn("60", _strip(_format_cpu("60.32%")))

    def test_high_cpu_over_100(self):
        # 180% (= 1.8 cores) rendered without crashing, integer format
        self.assertIn("180%", _strip(_format_cpu("180.45%")))

    def test_invalid_input_falls_back(self):
        # Should produce SOMETHING, not crash
        self.assertIsInstance(_format_cpu(""), str)


if __name__ == "__main__":
    unittest.main()
