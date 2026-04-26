"""CLI behavior for the --strict flag.

`--strict` promotes pipeline validation warnings (currently emitted by
the C7 ``validate`` cleanup stage — e.g. unexpected H1 count, heading
level skips) into a non-zero exit. Hard failures still take precedence
and exit 2; pure-warning runs under --strict exit 3.
"""

from __future__ import annotations

import subprocess
import sys


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "any2md", *args],
        capture_output=True,
        text=True,
    )


def test_strict_in_help():
    """The --strict flag must be advertised in --help."""
    r = _run("--help")
    assert r.returncode == 0
    assert "--strict" in r.stdout


def test_strict_exits_3_when_warnings(tmp_path):
    """A TXT body without an H1 trips the validator and, under --strict, exits 3."""
    src = tmp_path / "noh1.txt"
    src.write_text("body without H1\n")
    out = tmp_path / "out"
    r = _run("--strict", "-o", str(out), str(src))
    # The C7 validator emits "H1 count is 0 (expected 1)" → strict promotes
    # the warning to exit 3.
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"


def test_no_strict_succeeds_with_warnings(tmp_path):
    """Without --strict, the same input converts successfully (exit 0)."""
    src = tmp_path / "noh1.txt"
    src.write_text("body without H1\n")
    out = tmp_path / "out"
    r = _run("-o", str(out), str(src))
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
