"""Integration test: DOCX converter (Docling path)."""

import pytest
import yaml

from any2md._docling import has_docling
from any2md.converters.docx import convert_docx
from any2md.pipeline import PipelineOptions


pytestmark = pytest.mark.skipif(
    not has_docling(),
    reason="docling not installed",
)


def test_docx_docling_uses_structured_lane(fixture_dir, tmp_output_dir):
    ok = convert_docx(
        fixture_dir / "table_heavy.docx",
        tmp_output_dir,
        options=PipelineOptions(),
        force=True,
    )
    assert ok
    out = next(tmp_output_dir.glob("*.md")).read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    body = out[end + 5:]
    assert fm["extracted_via"] == "docling"
    assert "Header 1" in body  # Docling preserves table header
