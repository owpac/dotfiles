"""Tests for the CLI entry point — currently the `--completion` smoke test.

We don't drive the full subcommand dispatch through unit tests (each command
has its own test file). This file exists to guard the bits handled directly
by `main()`: argv parsing, the `--completion` short-circuit, and any future
top-level wiring.
"""

import contextlib
import io
import unittest
from unittest import mock

from kompose.__main__ import main


def _run(*argv) -> tuple[int, str]:
    """Invoke `main()` with the given argv and capture stdout."""
    buf = io.StringIO()
    with mock.patch("sys.argv", ["kompose", *argv]), contextlib.redirect_stdout(buf):
        rc = main()
    return rc, buf.getvalue()


class TestCompletion(unittest.TestCase):
    """`--completion zsh` should emit a usable zsh completion script."""

    def setUp(self):
        self.rc, self.out = _run("--completion", "zsh")

    def test_exits_zero(self):
        self.assertEqual(self.rc, 0)

    def test_emits_compdef_header(self):
        # First line in any usable zsh completion script.
        self.assertIn("#compdef kompose", self.out)

    def test_includes_dynamic_helpers(self):
        # The preamble wires service / container / host completion.
        for fn in ("_kompose_services", "_kompose_containers", "_kompose_hosts"):
            with self.subTest(fn=fn):
                self.assertIn(fn, self.out)

    def test_includes_upgrade_subcommand(self):
        # Regression guard — the original static completion file drifted and
        # missed `upgrade`. shtab pulls subcommands from argparse, so as long
        # as `upgrade` is registered it shows up here.
        self.assertIn("upgrade", self.out)


if __name__ == "__main__":
    unittest.main()
