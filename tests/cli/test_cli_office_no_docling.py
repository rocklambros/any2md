"""Without Docling, PowerPoint and Excel files fail one by one.

The batch keeps going: other files still convert and the run exits 2
(at least one file failed), not 1 (pre-flight error).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from any2md._docling import INSTALL_CMD, has_docling
from tests._office_fixtures import build_pptx, build_xlsx

pytestmark = pytest.mark.skipif(
    has_docling(), reason="checks the path taken when Docling is absent"
)


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "any2md", *args],
        capture_output=True,
        text=True,
    )


def test_scanned_office_files_fail_and_batch_continues(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    build_pptx(corpus / "deck.pptx", [("Title", "Body")])
    build_xlsx(corpus / "book.xlsx", {"S": [["a"]]})
    (corpus / "notes.txt").write_text("Plain notes.\n")
    out = tmp_path / "out"

    r = _run(str(corpus), "-o", str(out))

    assert r.returncode == 2, r.stdout + r.stderr
    fails = [line for line in r.stderr.splitlines() if line.startswith("  FAIL: ")]
    assert len(fails) == 2
    assert any("deck.pptx -- PPTX input needs Docling" in f for f in fails)
    assert any("book.xlsx -- XLSX input needs Docling" in f for f in fails)
    assert all(INSTALL_CMD in f for f in fails)
    assert (out / "notes.md").exists()
    assert "1 converted, 0 skipped, 2 failed" in r.stdout


def test_named_office_file_fails_with_install_hint(tmp_path):
    deck = build_pptx(tmp_path / "deck.pptx", [("Title", "Body")])

    r = _run(str(deck), "-o", str(tmp_path / "out"))

    assert r.returncode == 2
    assert (
        f"FAIL: deck.pptx -- PPTX input needs Docling, which is not installed. Install it with: {INSTALL_CMD}"
        in r.stderr
    )


def test_backend_mammoth_on_xlsx_fails_clearly(tmp_path):
    book = build_xlsx(tmp_path / "book.xlsx", {"S": [["a"]]})

    r = _run("--backend", "mammoth", str(book), "-o", str(tmp_path / "out"))

    assert r.returncode == 2
    assert "backend 'mammoth' is not valid for XLSX input" in r.stderr
