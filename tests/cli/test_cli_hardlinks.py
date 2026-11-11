"""Directory scans skip hard-linked files (CWE-62).

A hard link is a second name for the same file, so the no-follow open
cannot tell it apart from a regular file. Anyone who can write to a
scanned tree on a file system without protected hard links (macOS, or
Linux with ``fs.protected_hardlinks=0``) can run ``ln ~victim/.netrc
shared/notes.txt``, and a scan of ``shared/`` would copy the secret into
the output. Scanned files with more than one link are skipped. A file
named on the command line still converts, because the user chose it.
"""

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="hard-link semantics differ on Windows"
)

SECRET = "SECRET-SENTINEL-VALUE"


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "any2md", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def _all_output(out_dir):
    if not out_dir.exists():
        return ""
    # Upper-cased to match SECRET, because the text converter title-cases
    # a one-line file.
    return "".join(p.read_text() for p in out_dir.rglob("*.md")).upper()


@pytest.fixture
def linked_tree(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "netrc.txt"
    secret.write_text(f"{SECRET}\n")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "real.txt").write_text("Real document body.\n")
    os.link(secret, corpus / "notes.txt")
    return corpus, secret


def test_scan_skips_hard_linked_file(linked_tree, tmp_path):
    corpus, _ = linked_tree
    out = tmp_path / "out"

    r = _run("-o", str(out), str(corpus))

    assert r.returncode == 0, r.stderr
    assert (out / "real.md").exists()
    assert not (out / "notes.md").exists()
    assert SECRET not in _all_output(out)
    assert "SKIP (hard link)" in r.stderr
    assert "notes.txt" in r.stderr
    # The skip line tells the user how to convert the file on purpose.
    assert "command line" in r.stderr


def test_recursive_input_dir_scan_skips_hard_linked_file(linked_tree, tmp_path):
    corpus, secret = linked_tree
    (corpus / "sub").mkdir()
    os.link(secret, corpus / "sub" / "deep.txt")
    out = tmp_path / "out"

    r = _run("-o", str(out), "-r", "-i", str(corpus))

    assert r.returncode == 0, r.stderr
    assert not (out / "deep.md").exists()
    assert SECRET not in _all_output(out)
    assert r.stderr.count("SKIP (hard link)") == 2


def test_explicit_hard_linked_file_still_converts(linked_tree, tmp_path):
    corpus, _ = linked_tree
    out = tmp_path / "out"

    r = _run("-o", str(out), str(corpus / "notes.txt"))

    assert r.returncode == 0, r.stderr
    # The text converter title-cases a one-line file, so compare case-folded.
    assert SECRET.casefold() in (out / "notes.md").read_text().casefold()
    assert "SKIP (hard link)" not in r.stderr


def test_hard_link_skip_line_is_sanitized(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "netrc.txt"
    secret.write_text(f"{SECRET}\n")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    os.link(secret, corpus / "evil\x1b[31m\nFAKE: line.txt")
    out = tmp_path / "out"

    r = _run("-o", str(out), str(corpus))

    assert "SKIP (hard link)" in r.stderr
    assert "\x1b" not in r.stderr
    assert "\nFAKE: line" not in r.stderr
    assert SECRET not in _all_output(out)
