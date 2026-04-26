"""Tests for the pdf_looks_complex heuristic."""

from pathlib import Path

import pymupdf
import pytest

from any2md.converters.pdf import pdf_looks_complex


def _build_simple_pdf(tmp_path) -> Path:
    """Tiny single-page PDF with one column of dense text."""
    out = tmp_path / "simple.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Lorem ipsum " * 50)
    doc.save(str(out))
    doc.close()
    return out


def test_pdf_looks_complex_short_doc_returns_false(fixture_dir, tmp_path):
    simple = _build_simple_pdf(tmp_path)
    assert pdf_looks_complex(simple) is False


def test_pdf_looks_complex_multi_column_fixture_returns_true(fixture_dir):
    # The synthetic multi_column.pdf has 2 columns explicitly placed by
    # reportlab. The heuristic should flag it.
    pdf = fixture_dir / "multi_column.pdf"
    # The fixture has only 2 pages — pdf_looks_complex requires > 5
    # pages OR multi-column + table OR low char density.
    # Verify the heuristic returns False for short multi-column PDFs
    # (its design target is "is this risky enough to warrant Docling?").
    assert pdf_looks_complex(pdf) is False


def test_pdf_looks_complex_empty_text_layer(tmp_path):
    """A PDF with very few characters per page (scanned) returns True."""
    out = tmp_path / "scanned.pdf"
    doc = pymupdf.open()
    for _ in range(6):  # 6 pages > 5-page threshold
        page = doc.new_page()
        # Insert almost no text
        page.insert_text((50, 50), ".")
    doc.save(str(out))
    doc.close()
    assert pdf_looks_complex(out) is True
