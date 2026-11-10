"""Tests for --ocr-figures and --save-images flags."""

import subprocess
import sys


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "any2md", *args],
        capture_output=True,
        text=True,
    )


def test_ocr_figures_in_help():
    r = _run("--help")
    assert "--ocr-figures" in r.stdout


def test_save_images_in_help():
    r = _run("--help")
    assert "--save-images" in r.stdout


def test_flags_compose(fixture_dir, tmp_path):
    """Both flags parse together. They imply --high-fidelity, so without
    Docling the CLI must stop at pre-flight (exit 1) with the install
    hint; with Docling the conversion succeeds (exit 0)."""
    from any2md._docling import has_docling

    out_dir = tmp_path / "out"
    r = _run(
        "-o",
        str(out_dir),
        "--save-images",
        "--ocr-figures",
        str(fixture_dir / "ligatures_and_softhyphens.txt"),
    )
    assert "unrecognized arguments" not in r.stderr
    if has_docling():
        assert r.returncode == 0, r.stdout + r.stderr
    else:
        assert r.returncode == 1, r.stdout + r.stderr
        assert "any2md[high-fidelity]" in (r.stdout + r.stderr)
