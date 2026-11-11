"""Two inputs that map to the same output name must not clobber each other.

Output names come from the source stem, so ``a/report.txt`` and
``b/report.txt`` under ``-r``, or ``deck.txt`` next to ``deck.html``, all
write ``report.md`` or ``deck.md``. Before this check the second input was
reported as ``SKIP (exists)`` or, with ``--force``, overwrote the first.
"""

import subprocess
import sys


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "any2md", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def _tree(tmp_path):
    src = tmp_path / "src"
    (src / "a").mkdir(parents=True)
    (src / "b").mkdir()
    (src / "a" / "report.txt").write_text("Alpha text first.\n", encoding="utf-8")
    (src / "b" / "report.txt").write_text("Bravo text second.\n", encoding="utf-8")
    return src


def test_recursive_scan_collision_fails_the_later_file(tmp_path):
    out = tmp_path / "out"
    r = _run(str(_tree(tmp_path)), "-r", "-o", str(out))
    assert r.returncode == 2, r.stderr
    assert "FAIL" in r.stderr and "output name collision" in r.stderr
    assert "report.md" in r.stderr
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "Alpha" in md and "Bravo" not in md


def test_force_does_not_overwrite_an_output_from_the_same_run(tmp_path):
    out = tmp_path / "out"
    r = _run(str(_tree(tmp_path)), "-r", "-o", str(out), "--force")
    assert r.returncode == 2, r.stderr
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "Alpha" in md and "Bravo" not in md


def test_different_extensions_same_stem_collide(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "deck.txt").write_text("Plain deck text.\n", encoding="utf-8")
    (src / "deck.html").write_text(
        "<html><body><h1>Deck</h1><p>HTML deck body text.</p></body></html>",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    r = _run(str(src), "-o", str(out))
    assert r.returncode == 2, r.stderr
    assert "output name collision" in r.stderr
    assert (out / "deck.md").exists()


def test_case_only_difference_collides(tmp_path):
    # macOS and Windows file systems ignore case by default, so Report.md
    # and report.md are the same file there.
    src = tmp_path / "src"
    (src / "a").mkdir(parents=True)
    (src / "b").mkdir()
    (src / "a" / "Report.txt").write_text("Upper case name.\n", encoding="utf-8")
    (src / "b" / "report.txt").write_text("Lower case name.\n", encoding="utf-8")
    r = _run(str(src), "-r", "-o", str(tmp_path / "out"))
    assert r.returncode == 2, r.stderr
    assert "output name collision" in r.stderr


def test_distinct_names_still_convert(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "one.txt").write_text("First file.\n", encoding="utf-8")
    (src / "two.txt").write_text("Second file.\n", encoding="utf-8")
    r = _run(str(src), "-o", str(tmp_path / "out"))
    assert r.returncode == 0, r.stderr
    assert "collision" not in r.stderr


def test_skipped_hard_link_does_not_claim_the_name(tmp_path):
    # a/report.txt is skipped as a hard link, so b/report.txt owns the name.
    src = tmp_path / "src"
    (src / "a").mkdir(parents=True)
    (src / "b").mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("Outside text.\n", encoding="utf-8")
    (src / "a" / "report.txt").hardlink_to(outside)
    (src / "b" / "report.txt").write_text("Bravo text second.\n", encoding="utf-8")
    out = tmp_path / "out"
    r = _run(str(src), "-r", "-o", str(out))
    assert r.returncode == 0, r.stderr
    assert "collision" not in r.stderr
    assert "Bravo" in (out / "report.md").read_text(encoding="utf-8")


def test_skipped_large_file_does_not_claim_the_name(tmp_path):
    src = tmp_path / "src"
    (src / "a").mkdir(parents=True)
    (src / "b").mkdir()
    (src / "a" / "report.txt").write_text("Large text. " * 200, encoding="utf-8")
    (src / "b" / "report.txt").write_text("Bravo small.\n", encoding="utf-8")
    out = tmp_path / "out"
    r = _run(str(src), "-r", "-o", str(out), "--max-file-size", "500")
    assert r.returncode == 0, r.stderr
    assert "SKIP (too large)" in r.stderr
    assert "collision" not in r.stderr
    assert "Bravo" in (out / "report.md").read_text(encoding="utf-8")


def test_skipped_named_large_file_does_not_claim_the_name(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    big = tmp_path / "a" / "report.txt"
    big.write_text("Large text. " * 200, encoding="utf-8")
    small = tmp_path / "b" / "report.txt"
    small.write_text("Bravo small.\n", encoding="utf-8")
    out = tmp_path / "out"
    r = _run(str(big), str(small), "-o", str(out), "--max-file-size", "500")
    assert r.returncode == 0, r.stderr
    assert "collision" not in r.stderr
    assert "Bravo" in (out / "report.md").read_text(encoding="utf-8")


def test_same_file_named_twice_converts_once(tmp_path):
    f = tmp_path / "one.txt"
    f.write_text("First file.\n", encoding="utf-8")
    r = _run(str(f), str(f), "-o", str(tmp_path / "out"))
    assert r.returncode == 0, r.stderr
    assert "collision" not in r.stderr
    assert "1 converted" in r.stdout


def test_directory_and_file_inside_it_convert_once(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    f = src / "one.txt"
    f.write_text("First file.\n", encoding="utf-8")
    r = _run(str(src), str(f), "-o", str(tmp_path / "out"))
    assert r.returncode == 0, r.stderr
    assert "collision" not in r.stderr
    assert "1 converted" in r.stdout


def test_existing_output_still_reports_collision_before_exists(tmp_path):
    # The second file of a colliding pair must FAIL, not SKIP (exists),
    # even though the first one has written report.md by then.
    out = tmp_path / "out"
    r = _run(str(_tree(tmp_path)), "-r", "-o", str(out))
    assert "SKIP (exists)" not in r.stdout
    assert "output name collision" in r.stderr
