"""CLI smoke: existing v0.7 flags still work and route through v1.0 pipeline."""

import subprocess
import sys


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "any2md", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def test_help_works():
    r = _run("--help")
    assert r.returncode == 0
    assert "any2md" in r.stdout.lower()
    assert "--strip-links" in r.stdout


def test_force_flag_overwrites(fixture_dir, tmp_output_dir):
    fixture = str(fixture_dir / "ligatures_and_softhyphens.txt")
    r1 = _run("-o", str(tmp_output_dir), fixture)
    assert r1.returncode == 0, r1.stderr
    r2 = _run("-o", str(tmp_output_dir), fixture)  # skip-existing
    assert "SKIP" in (r2.stdout + r2.stderr)
    r3 = _run("-o", str(tmp_output_dir), "--force", fixture)
    assert r3.returncode == 0, r3.stderr
    assert "OK" in (r3.stdout + r3.stderr) or "Done" in (r3.stdout + r3.stderr)


def _body(md_path):
    text = md_path.read_text()
    return text[text.index("\n---\n", 4) + 5 :]


def test_strip_links_removes_link_urls(tmp_path):
    src = tmp_path / "links.txt"
    src.write_text("Intro\n=====\n\nSee [the docs](https://example.com/docs) now.\n")
    out = tmp_path / "out"
    r = _run("-o", str(out), "--strip-links", str(src))
    assert r.returncode == 0, r.stderr
    body = _body(out / "links.md")
    assert "See the docs now." in body
    assert "example.com" not in body


def test_profile_maximum_implies_strip_links(tmp_path):
    src = tmp_path / "links.txt"
    src.write_text("Intro\n=====\n\nSee [the docs](https://example.com/docs) now.\n")
    out = tmp_path / "out"
    r = _run("-o", str(out), "--profile", "maximum", str(src))
    assert r.returncode == 0, r.stderr
    assert "example.com" not in _body(out / "links.md")


def test_links_kept_without_flag(tmp_path):
    src = tmp_path / "links.txt"
    src.write_text("Intro\n=====\n\nSee [the docs](https://example.com/docs) now.\n")
    out = tmp_path / "out"
    r = _run("-o", str(out), str(src))
    assert r.returncode == 0, r.stderr
    assert "[the docs](https://example.com/docs)" in _body(out / "links.md")
