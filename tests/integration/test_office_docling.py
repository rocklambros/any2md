"""Integration: PowerPoint and Excel files through the real Docling backends."""

from __future__ import annotations

import pytest

pytest.importorskip("docling")

from any2md._safe_open import SourceFile  # noqa: E402
from any2md.converters import convert_file  # noqa: E402
from any2md.pipeline import PipelineOptions  # noqa: E402
from tests._office_fixtures import build_pptx, build_xlsx  # noqa: E402


def _split(md_text: str) -> tuple[str, str]:
    end = md_text.index("\n---\n", 4)
    return md_text[:end], md_text[end + 5 :]


def _headings(body: str) -> list[str]:
    return [line for line in body.splitlines() if line.startswith("#")]


def test_pptx_slides_become_sections(tmp_path):
    deck = build_pptx(
        tmp_path / "deck.pptx",
        [
            ("Quarterly Review", "Revenue grew 12 percent."),
            (None, "A slide with no title."),
            ("Next Steps", "Hire two engineers."),
        ],
        title="Q3 Deck",
    )
    out = tmp_path / "out"

    assert convert_file(deck, out, options=PipelineOptions(), force=True)

    fm, body = _split((out / "deck.md").read_text(encoding="utf-8"))
    assert 'type: "pptx"' in fm
    assert 'extracted_via: "docling"' in fm
    assert 'title: "Q3 Deck"' in fm
    assert _headings(body) == [
        "# Q3 Deck",
        "## Quarterly Review",
        "## Slide 2",
        "## Next Steps",
    ]
    assert "Revenue grew 12 percent." in body
    assert "A slide with no title." in body


def test_xlsx_sheets_render_as_tables_under_headings(tmp_path):
    book = build_xlsx(
        tmp_path / "budget.xlsx",
        {
            "Revenue": [["Region", "Q1"], ["North", "10"]],
            "Staff": [["Team", "Count"], ["Eng", "5"]],
        },
    )
    out = tmp_path / "out"

    assert convert_file(book, out, options=PipelineOptions(), force=True)

    fm, body = _split((out / "budget.md").read_text(encoding="utf-8"))
    assert 'type: "xlsx"' in fm
    assert _headings(body) == ["# budget", "## Revenue", "## Staff"]
    assert "| Region | Q1 |" in body
    assert "| Eng | 5 |" in body


def test_bytes_backed_source_converts(tmp_path):
    """A scanned file arrives as bytes and reaches Docling as a stream."""
    path = build_xlsx(tmp_path / "scan.xlsx", {"S": [["k", "v"], ["a", "1"]]})
    src = SourceFile("scan.xlsx", data=path.read_bytes(), mtime=0.0)
    path.unlink()
    out = tmp_path / "out"

    assert convert_file(src, out, options=PipelineOptions(), force=True)
    assert "| a | 1 |" in (out / "scan.md").read_text(encoding="utf-8")


def test_content_not_matching_extension_is_rejected(tmp_path, capsys):
    """A workbook renamed to .pptx must not reach another Docling backend."""
    book = build_xlsx(tmp_path / "real.xlsx", {"S": [["a"]]})
    fake = tmp_path / "fake.pptx"
    fake.write_bytes(book.read_bytes())

    assert convert_file(fake, tmp_path / "out", force=True) is False
    assert "FAIL: fake.pptx -- Docling could not convert" in capsys.readouterr().err


def test_corrupt_file_fails_cleanly(tmp_path, capsys):
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"PK\x03\x04 truncated archive")

    assert convert_file(bad, tmp_path / "out", force=True) is False
    # Docling logs its own complaint to stderr as well, so look for the
    # one FAIL line any2md writes.
    fails = [
        line
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("  FAIL: ")
    ]
    assert len(fails) == 1
    # The zip guard refuses it before Docling opens it.
    assert fails[0] == "  FAIL: bad.xlsx -- not a valid OOXML (zip) archive"
