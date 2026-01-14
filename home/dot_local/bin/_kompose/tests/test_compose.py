"""Tests for compose module."""

import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from _kompose.compose import (
    parse_ip_for_sort,
    get_compose_files,
    build_compose_command,
)


class TestParseIpForSort(unittest.TestCase):
    def test_parse_valid_ip(self):
        result = parse_ip_for_sort("10.10.10.5")
        self.assertEqual(result, (10, 10, 10, 5))

    def test_parse_ip_sorts_correctly(self):
        ips = ["10.10.10.20", "10.10.10.5", "10.10.10.100", "10.10.10.2"]
        sorted_ips = sorted(ips, key=parse_ip_for_sort)
        self.assertEqual(sorted_ips, ["10.10.10.2", "10.10.10.5", "10.10.10.20", "10.10.10.100"])

    def test_parse_empty_ip(self):
        result = parse_ip_for_sort("")
        self.assertEqual(result, (999, 999, 999, 999))

    def test_parse_none_ip(self):
        result = parse_ip_for_sort(None)
        self.assertEqual(result, (999, 999, 999, 999))

    def test_empty_ips_sort_last(self):
        ips = ["10.10.10.5", "", "10.10.10.2", ""]
        sorted_ips = sorted(ips, key=parse_ip_for_sort)
        self.assertEqual(sorted_ips, ["10.10.10.2", "10.10.10.5", "", ""])


class TestBuildComposeCommand(unittest.TestCase):
    def test_build_basic_command(self):
        files = [Path("/path/to/compose.yml")]
        cmd = build_compose_command(files, "up")
        self.assertEqual(cmd, ["docker", "compose", "-f", "/path/to/compose.yml", "up"])

    def test_build_command_multiple_files(self):
        files = [Path("/base/compose.yml"), Path("/host/compose.yml")]
        cmd = build_compose_command(files, "up")
        self.assertEqual(cmd, [
            "docker", "compose",
            "-f", "/base/compose.yml",
            "-f", "/host/compose.yml",
            "up"
        ])

    def test_build_command_with_extra_args(self):
        files = [Path("/path/compose.yml")]
        cmd = build_compose_command(files, "up", ["-d", "--build"])
        self.assertEqual(cmd, ["docker", "compose", "-f", "/path/compose.yml", "up", "-d", "--build"])

    def test_build_command_no_extra_args(self):
        files = [Path("/path/compose.yml")]
        cmd = build_compose_command(files, "down", None)
        self.assertEqual(cmd, ["docker", "compose", "-f", "/path/compose.yml", "down"])


if __name__ == "__main__":
    unittest.main()
