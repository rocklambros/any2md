"""Directory scans must not follow symlinks (F14 CWE-59, F22 CWE-61).

An untrusted document tree can carry a link such as ``report.txt ->
~/.ssh/id_rsa``. Following it during a scan copies the target into the
converted output. Explicit command-line paths stay honored because the
user chose them.
"""

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="symlink creation needs privileges on Windows"
)

SECRET = "SECRET-SENTINEL-VALUE"


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "any2md", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def _secret_file(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "id_rsa"
    secret.write_text(f"{SECRET}\n")
    return secret


def _all_output(out_dir):
    if not out_dir.exists():
        return ""
    return "".join(p.read_text() for p in out_dir.rglob("*.md"))


def test_scan_skips_symlinked_file(tmp_path):
    secret = _secret_file(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "real.txt").write_text("Real document body.\n")
    os.symlink(secret, corpus / "report.txt")
    out = tmp_path / "out"

    r = _run("-o", str(out), str(corpus))

    assert r.returncode == 0, r.stderr
    assert (out / "real.md").exists()
    assert not (out / "report.md").exists()
    assert SECRET not in _all_output(out)
    assert "SKIP (symlink)" in r.stderr
    assert "report.txt" in r.stderr


def test_input_dir_scan_skips_symlinked_file(tmp_path):
    secret = _secret_file(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "real.txt").write_text("Real document body.\n")
    os.symlink(secret, corpus / "report.txt")
    out = tmp_path / "out"

    r = _run("-o", str(out), "-i", str(corpus))

    assert r.returncode == 0, r.stderr
    assert (out / "real.md").exists()
    assert not (out / "report.md").exists()
    assert SECRET not in _all_output(out)
    assert "SKIP (symlink)" in r.stderr


def test_default_cwd_scan_skips_symlinked_file(tmp_path):
    secret = _secret_file(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "real.txt").write_text("Real document body.\n")
    os.symlink(secret, corpus / "report.txt")
    out = tmp_path / "out"

    r = _run("-o", str(out), cwd=corpus)

    assert r.returncode == 0, r.stderr
    assert (out / "real.md").exists()
    assert not (out / "report.md").exists()
    assert SECRET not in _all_output(out)


def test_recursive_scan_does_not_descend_into_symlinked_dir(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text(f"{SECRET}\n")
    corpus = tmp_path / "corpus"
    (corpus / "sub").mkdir(parents=True)
    (corpus / "sub" / "nested.txt").write_text("Nested document body.\n")
    os.symlink(outside, corpus / "linked", target_is_directory=True)
    out = tmp_path / "out"

    r = _run("-o", str(out), "-r", str(corpus))

    assert r.returncode == 0, r.stderr
    assert (out / "nested.md").exists()
    assert not (out / "private.md").exists()
    assert SECRET not in _all_output(out)
    assert "SKIP (symlink)" in r.stderr
    assert "linked" in r.stderr


def test_recursive_scan_survives_symlink_loop(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "doc.txt").write_text("Loop document body.\n")
    os.symlink(corpus, corpus / "loop", target_is_directory=True)
    out = tmp_path / "out"

    r = _run("-o", str(out), "-r", str(corpus))

    assert r.returncode == 0, r.stderr
    assert (out / "doc.md").exists()
    assert "Done in" in r.stdout
    assert "1 converted" in r.stdout
    assert "SKIP (symlink)" in r.stderr


def test_skip_notice_is_sanitized(tmp_path):
    secret = _secret_file(tmp_path)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    os.symlink(secret, corpus / "evil\x1b[31m\nFAKE: line.txt")
    out = tmp_path / "out"

    r = _run("-o", str(out), str(corpus))

    assert r.returncode == 0, r.stderr
    assert "SKIP (symlink)" in r.stderr
    assert "\x1b" not in r.stderr
    assert "\nFAKE: line" not in r.stderr
    assert SECRET not in _all_output(out)


def test_explicit_symlink_argument_still_converts(tmp_path):
    target_dir = tmp_path / "elsewhere"
    target_dir.mkdir()
    target = target_dir / "chosen.txt"
    target.write_text("Chosen document body.\n")
    link = tmp_path / "pointer.txt"
    os.symlink(target, link)
    out = tmp_path / "out"

    r = _run("-o", str(out), str(link))

    assert r.returncode == 0, r.stderr
    assert (out / "pointer.md").exists()
    assert "Chosen document body." in (out / "pointer.md").read_text()
    assert "SKIP (symlink)" not in r.stderr


def test_explicit_symlinked_directory_argument_is_scanned(tmp_path):
    real = tmp_path / "real_corpus"
    real.mkdir()
    (real / "inside.txt").write_text("Inside document body.\n")
    link = tmp_path / "corpus_link"
    os.symlink(real, link, target_is_directory=True)
    out = tmp_path / "out"

    r = _run("-o", str(out), str(link))

    assert r.returncode == 0, r.stderr
    assert (out / "inside.md").exists()
