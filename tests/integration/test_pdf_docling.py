"""Integration test: PDF converter (Docling path)."""

import pytest
import yaml

from any2md._docling import has_docling
from any2md.converters.pdf import convert_pdf
from any2md.pipeline import PipelineOptions


pytestmark = pytest.mark.skipif(
    not has_docling(),
    reason="docling not installed (test runs only when [high-fidelity] is installed)",
)


def test_pdf_docling_emits_v1_frontmatter_structured_lane(fixture_dir, tmp_output_dir):
    ok = convert_pdf(
        fixture_dir / "multi_column.pdf",
        tmp_output_dir,
        options=PipelineOptions(high_fidelity=True),
        force=True,
    )
    assert ok
    out_files = list(tmp_output_dir.glob("*.md"))
    assert len(out_files) == 1
    out = out_files[0].read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    assert fm["status"] == "draft"
    assert fm["extracted_via"] == "docling"
    assert fm["pages"] == 2
    assert fm["content_hash"]


def test_pdf_default_uses_docling_when_installed(fixture_dir, tmp_output_dir):
    """Without -H but with Docling installed, we still pick Docling."""
    ok = convert_pdf(
        fixture_dir / "multi_column.pdf",
        tmp_output_dir,
        options=PipelineOptions(),  # default: high_fidelity False, but Docling auto-used
        force=True,
    )
    assert ok
    out = next(tmp_output_dir.glob("*.md")).read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    assert fm["extracted_via"] == "docling"
