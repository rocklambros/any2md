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
    monkeypatch.setattr("any2md.converters.pdf.has_docling", lambda: False)
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
    body = out[end + 5 :]
    assert fm["status"] == "draft"
    assert fm["extracted_via"] == "pymupdf4llm"
    assert fm["pages"] == 2
    assert fm["content_hash"]
    assert "Lorem ipsum" in body
    # v1.0.2: filter_organization routes Creator metadata. The synthetic
    # fixture's Creator field is "anonymous" (not software), so the value
    # appears in `organization`; `produced_by` is omitted from frontmatter
    # because it's None.
    assert fm["organization"] == "anonymous"
    assert "produced_by" not in fm


def test_pdf_software_creator_routes_to_produced_by(
    fixture_dir, tmp_output_dir, monkeypatch
):
    """When PDF Creator is software, organization is empty and produced_by populated."""
    monkeypatch.setattr("any2md.converters.pdf.has_docling", lambda: False)
    # Patch the metadata parser to simulate a software-creator PDF.
    from any2md.converters import pdf as pdf_mod

    real = pdf_mod._parse_pdf_metadata

    def fake(doc):
        out = real(doc)
        # Re-route through filter_organization with a software value.
        from any2md.heuristics import filter_organization

        result = filter_organization("Adobe InDesign 16.2 (Windows)")
        out["organization"] = result.organization
        out["produced_by"] = result.produced_by
        return out

    monkeypatch.setattr(pdf_mod, "_parse_pdf_metadata", fake)
    ok = convert_pdf(
        fixture_dir / "multi_column.pdf",
        tmp_output_dir,
        options=PipelineOptions(),
        force=True,
    )
    assert ok
    out = next(tmp_output_dir.glob("*.md")).read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    assert fm["organization"] == ""  # empty when software-creator
    assert fm["produced_by"] == "Adobe InDesign 16.2 (Windows)"
