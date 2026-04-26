"""Integration test: DOCX converter (mammoth fallback path).

Docling is now the default backend when installed. This test simulates
the no-Docling environment by monkeypatching `has_docling` to return
False so the mammoth fallback path is exercised regardless of install
state.
"""

import yaml

from any2md.converters.docx import convert_docx
from any2md.pipeline import PipelineOptions


def test_docx_emits_v1_frontmatter_with_core_props(
    fixture_dir, tmp_output_dir, monkeypatch
):
    monkeypatch.setattr(
        "any2md.converters.docx.has_docling", lambda: False
    )
    ok = convert_docx(
        fixture_dir / "table_heavy.docx",
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
    assert fm["title"] == "Table Heavy Test Document"
    assert fm["authors"] == ["Test Author"]
    assert fm["organization"] == "Test Org"
    assert fm["date"] == "2026-04-26"
    assert "tables" in fm.get("keywords", [])
    assert fm["extracted_via"] == "mammoth+markdownify"
    assert fm["status"] == "draft"
    # Body has table content
    assert "Header 1" in body and "Cell A" in body
