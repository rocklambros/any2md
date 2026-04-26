"""Tests for the ``--backend`` CLI flag."""

import subprocess
import sys

import yaml


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "any2md", *args],
        capture_output=True,
        text=True,
    )


def test_backend_in_help():
    r = _run("--help")
    assert r.returncode == 0
    assert "--backend" in r.stdout
    assert "docling" in r.stdout
    assert "pymupdf4llm" in r.stdout
    assert "mammoth" in r.stdout


def test_backend_pymupdf4llm_forces_via_cli(fixture_dir, tmp_path):
    out = tmp_path / "out"
    r = _run(
        "--backend",
        "pymupdf4llm",
        "-o",
        str(out),
        str(fixture_dir / "multi_column.pdf"),
    )
    assert r.returncode == 0, r.stdout + r.stderr
    md = next(out.glob("*.md")).read_text()
    end = md.index("\n---\n", 4)
    fm = yaml.safe_load(md[4:end])
    assert fm["extracted_via"] == "pymupdf4llm"


def test_backend_invalid_choice():
    r = _run("--backend", "bogus", "-o", "/tmp/x", "fake.pdf")
    assert r.returncode != 0
    assert "invalid choice" in (r.stdout + r.stderr).lower()
