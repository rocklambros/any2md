"""Tests for the --high-fidelity / -H CLI flag."""

import subprocess
import sys


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "any2md", *args],
        capture_output=True, text=True,
    )


def test_high_fidelity_flag_present_in_help():
    r = _run("--help")
    assert r.returncode == 0
    assert "--high-fidelity" in r.stdout or "-H" in r.stdout


def test_high_fidelity_short_flag_present_in_help():
    r = _run("--help")
    assert "-H" in r.stdout


def test_high_fidelity_without_docling_exits_one(monkeypatch, fixture_dir, tmp_path):
    """If Docling isn't installed and -H is set, exit 1 with hint."""
    # Skip if docling IS installed — then this test isn't meaningful here.
    from any2md._docling import has_docling
    if has_docling():
        import pytest
        pytest.skip("docling installed; this assertion only meaningful without")

    out_dir = tmp_path / "out"
    r = _run(
        "-H", "-o", str(out_dir),
        str(fixture_dir / "ligatures_and_softhyphens.txt"),
    )
    assert r.returncode == 1
    assert "any2md[high-fidelity]" in (r.stdout + r.stderr)
