"""CLI behavior for the --quiet and --verbose output flags."""

from __future__ import annotations

import subprocess
import sys


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "any2md", *args],
        capture_output=True,
        text=True,
    )


def test_quiet_in_help():
    r = _run("--help")
    assert r.returncode == 0
    assert "--quiet" in r.stdout


def test_quiet_suppresses_per_file_ok(fixture_dir, tmp_path):
    """Per-file ``OK:`` lines disappear under --quiet; the run still succeeds."""
    out = tmp_path / "out"
    r = _run("-q", "-o", str(out), str(fixture_dir / "ligatures_and_softhyphens.txt"))
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "OK:" not in r.stdout


def test_verbose_in_help():
    r = _run("--help")
    assert r.returncode == 0
    assert "--verbose" in r.stdout
