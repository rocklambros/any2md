"""End-to-end test for the CLI ``--meta KEY=VAL`` flag.

Confirms that values supplied on the command line replace derived
frontmatter fields in the emitted Markdown.
"""

from __future__ import annotations

import subprocess
import sys

import yaml


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "any2md", *args],
        capture_output=True,
        text=True,
    )


def test_meta_simple_override(fixture_dir, tmp_path):
    out = tmp_path / "out"
    r = _run(
        "-o",
        str(out),
        "--meta",
        "organization=OWASP",
        str(fixture_dir / "ligatures_and_softhyphens.txt"),
    )
    assert r.returncode == 0, r.stderr
    md = (out / "ligatures_and_softhyphens.md").read_text()
    end = md.index("\n---\n", 4)
    fm = yaml.safe_load(md[4:end])
    assert fm["organization"] == "OWASP"


def test_meta_nested_key_with_list_value(fixture_dir, tmp_path):
    out = tmp_path / "out"
    r = _run(
        "-o",
        str(out),
        "--meta",
        "review.approvers=x,y",
        str(fixture_dir / "ligatures_and_softhyphens.txt"),
    )
    assert r.returncode == 0, r.stderr
    md = (out / "ligatures_and_softhyphens.md").read_text()
    end = md.index("\n---\n", 4)
    fm = yaml.safe_load(md[4:end])
    assert fm["review"] == {"approvers": ["x", "y"]}


def test_emission_error_fails_each_file_without_ending_batch(tmp_path):
    # A TOML date has no YAML emitter, so every file fails at emission.
    # Each failure must be reported and the run must reach the summary.
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("First file body.\n")
    (src / "b.txt").write_text("Second file body.\n")
    meta_file = tmp_path / "meta.toml"
    meta_file.write_text("[meta]\nreviewed = 2026-01-01\n")
    r = _run(
        "-o",
        str(tmp_path / "out"),
        "--no-config",
        "--meta-file",
        str(meta_file),
        str(src / "a.txt"),
        str(src / "b.txt"),
    )
    assert "Traceback" not in r.stderr, r.stderr
    assert "FAIL: a.txt" in r.stderr
    assert "FAIL: b.txt" in r.stderr
    assert "2 failed" in r.stdout
    assert r.returncode == 2
