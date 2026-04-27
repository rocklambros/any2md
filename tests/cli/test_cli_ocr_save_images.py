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
    """Both flags accepted together. With Docling absent they have no
    effect on backend selection but must not error on argparse."""
    out_dir = tmp_path / "out"
    r = _run(
        "-o",
        str(out_dir),
        "--save-images",
        "--ocr-figures",
        str(fixture_dir / "ligatures_and_softhyphens.txt"),
    )
    # TXT input is unaffected by these flags but the CLI must still parse them
    assert r.returncode == 0
