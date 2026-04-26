"""Integration tests for ``PipelineOptions.backend`` on PDF conversions.

The ``backend`` field forces a specific extraction backend, overriding
the automatic Docling-when-installed selection. ``"mammoth"`` is invalid
for PDFs and must error per file.
"""

import pytest
import yaml

from any2md._docling import has_docling
from any2md.converters.pdf import convert_pdf
from any2md.pipeline import PipelineOptions


def _fm(out_dir):
    text = next(out_dir.glob("*.md")).read_text()
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end])


def test_pdf_backend_pymupdf4llm_forces_fallback(fixture_dir, tmp_output_dir):
    """Even with Docling installed, --backend pymupdf4llm uses pymupdf4llm."""
    ok = convert_pdf(
        fixture_dir / "multi_column.pdf",
        tmp_output_dir,
        options=PipelineOptions(backend="pymupdf4llm"),
        force=True,
    )
    assert ok
    fm = _fm(tmp_output_dir)
    assert fm["extracted_via"] == "pymupdf4llm"


@pytest.mark.skipif(not has_docling(), reason="docling not installed")
def test_pdf_backend_docling_explicit(fixture_dir, tmp_output_dir):
    ok = convert_pdf(
        fixture_dir / "multi_column.pdf",
        tmp_output_dir,
        options=PipelineOptions(backend="docling"),
        force=True,
    )
    assert ok
    fm = _fm(tmp_output_dir)
    assert fm["extracted_via"] == "docling"


def test_pdf_backend_mammoth_is_invalid(fixture_dir, tmp_output_dir, capsys):
    ok = convert_pdf(
        fixture_dir / "multi_column.pdf",
        tmp_output_dir,
        options=PipelineOptions(backend="mammoth"),
        force=True,
    )
    assert ok is False
    captured = capsys.readouterr()
    assert "mammoth" in (captured.out + captured.err).lower()
