"""A tree changed between the directory scan and the read cannot redirect it.

Each test wraps ``cli._scan_directory`` so the swap happens after the
scan has returned and before the main loop opens the file. That is the
race window from the PR #47 review, made deterministic.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap

import pytest

from any2md import cli

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="symlink creation needs privileges on Windows"
)

SECRET = "SECRET-SENTINEL-VALUE"


def _all_output(out_dir):
    if not out_dir.exists():
        return ""
    return "".join(p.read_text() for p in out_dir.rglob("*.md"))


@pytest.fixture
def tree(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "report.txt").write_text(f"{SECRET}\n")
    (outside / "nested.txt").write_text(f"{SECRET}\n")
    corpus = tmp_path / "corpus"
    (corpus / "sub").mkdir(parents=True)
    (corpus / "real.txt").write_text("Real document body.\n")
    (corpus / "report.txt").write_text("Report body before the swap.\n")
    (corpus / "sub" / "nested.txt").write_text("Nested body before the swap.\n")
    return corpus, outside


def _run_main_with_swap(monkeypatch, argv, swap):
    real_scan = cli._scan_directory

    def scan_then_swap(root, recursive):
        found = real_scan(root, recursive)
        swap()
        return found

    monkeypatch.setattr(cli, "_scan_directory", scan_then_swap)
    monkeypatch.setattr(sys, "argv", ["any2md", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return exc.value.code


def test_file_swapped_for_symlink_after_scan_is_skipped(
    tree, tmp_path, monkeypatch, capsys
):
    corpus, outside = tree
    out = tmp_path / "out"

    def swap():
        (corpus / "report.txt").unlink()
        os.symlink(outside / "report.txt", corpus / "report.txt")

    code = _run_main_with_swap(monkeypatch, ["-o", str(out), str(corpus)], swap)
    err = capsys.readouterr().err

    assert code == 0, err
    assert (out / "real.md").exists()
    assert not (out / "report.md").exists()
    assert SECRET not in _all_output(out)
    assert "SKIP (symlink)" in err
    assert "report.txt" in err


def test_parent_dir_swapped_for_symlink_after_scan_is_skipped(
    tree, tmp_path, monkeypatch, capsys
):
    corpus, outside = tree
    out = tmp_path / "out"

    def swap():
        shutil.rmtree(corpus / "sub")
        os.symlink(outside, corpus / "sub", target_is_directory=True)

    code = _run_main_with_swap(
        monkeypatch, ["-o", str(out), "-r", "-i", str(corpus)], swap
    )
    err = capsys.readouterr().err

    assert code == 0, err
    assert (out / "real.md").exists()
    assert not (out / "nested.md").exists()
    assert SECRET not in _all_output(out)
    assert "SKIP (symlink)" in err


def test_default_cwd_scan_is_bound_too(tree, tmp_path, monkeypatch, capsys):
    corpus, outside = tree
    out = tmp_path / "out"
    monkeypatch.chdir(corpus)

    def swap():
        (corpus / "report.txt").unlink()
        os.symlink(outside / "report.txt", corpus / "report.txt")

    code = _run_main_with_swap(monkeypatch, ["-o", str(out)], swap)
    err = capsys.readouterr().err

    assert code == 0, err
    assert SECRET not in _all_output(out)
    assert "SKIP (symlink)" in err


def test_skip_line_for_swapped_file_is_sanitized(tree, tmp_path, monkeypatch, capsys):
    corpus, outside = tree
    hostile = corpus / "evil\x1b[31m\nFAKE: line.txt"
    hostile.write_text("Hostile name body.\n")
    out = tmp_path / "out"

    def swap():
        hostile.unlink()
        os.symlink(outside / "report.txt", hostile)

    _run_main_with_swap(monkeypatch, ["-o", str(out), str(corpus)], swap)
    err = capsys.readouterr().err

    assert "SKIP (symlink)" in err
    assert "\x1b" not in err
    assert "\nFAKE: line" not in err
    assert SECRET not in _all_output(out)


def test_explicit_file_argument_still_follows_link(tmp_path, monkeypatch, capsys):
    target = tmp_path / "elsewhere" / "chosen.txt"
    target.parent.mkdir()
    target.write_text("Chosen document body.\n")
    link = tmp_path / "pointer.txt"
    os.symlink(target, link)
    out = tmp_path / "out"

    code = _run_main_with_swap(monkeypatch, ["-o", str(out), str(link)], lambda: None)

    assert code == 0, capsys.readouterr().err
    assert "Chosen document body." in (out / "pointer.md").read_text()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs os.mkfifo")
def test_fifo_swapped_in_after_scan_does_not_hang(tree, tmp_path):
    corpus, _ = tree
    out = tmp_path / "out"
    # The driver runs the real CLI in a child process so a regression that
    # blocks on the FIFO open fails on the timeout instead of hanging pytest.
    driver = textwrap.dedent(
        """
        import os, sys
        from pathlib import Path
        from any2md import cli

        corpus = Path(sys.argv[1])
        real_scan = cli._scan_directory

        def scan_then_swap(root, recursive):
            found = real_scan(root, recursive)
            (corpus / "report.txt").unlink()
            os.mkfifo(corpus / "report.txt")
            return found

        cli._scan_directory = scan_then_swap
        sys.argv = ["any2md", "-o", sys.argv[2], str(corpus)]
        cli.main()
        """
    )
    r = subprocess.run(
        [sys.executable, "-c", driver, str(corpus), str(out)],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert r.returncode == 0, r.stderr
    assert "SKIP (not a regular file)" in r.stderr
    assert (out / "real.md").exists()
    assert not (out / "report.md").exists()
