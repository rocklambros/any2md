"""Integration test: PDF converter (pymupdf4llm fallback path).

Docling is now the default backend when installed. This test simulates
the no-Docling environment by monkeypatching `has_docling` to return
False so the fallback path is exercised regardless of install state.
"""

import yaml

from any2md.converters.pdf import convert_pdf
from any2md.pipeline import PipelineOptions


def test_pdf_emits_v1_frontmatter_pymupdf_path(
    fixture_dir, tmp_output_dir, monkeypatch
):
    monkeypatch.setattr(
        "any2md.converters.pdf.has_docling", lambda: False
    )
    ok = convert_pdf(
        fixture_dir / "multi_column.pdf",
        tmp_output_dir,
        options=PipelineOptions(),
        force=True,
    )
    assert ok
    out_files = list(tmp_output_dir.glob("*.md"))
    assert len(out_files) == 1
    out = out_files[0].read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    body = out[end + 5:]
    assert fm["status"] == "draft"
    assert fm["extracted_via"] == "pymupdf4llm"
    assert fm["pages"] == 2
    assert fm["content_hash"]
    assert "Lorem ipsum" in body
