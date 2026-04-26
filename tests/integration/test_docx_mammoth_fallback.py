"""Integration test: DOCX converter (mammoth fallback path).

Docling is now the default backend when installed. This test simulates
the no-Docling environment by monkeypatching `has_docling` to return
False so the mammoth fallback path is exercised regardless of install
state.
"""

import zipfile
from pathlib import Path

import yaml

from any2md.converters.docx import convert_docx
from any2md.pipeline import PipelineOptions


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""

_CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/"
                   xmlns:dcterms="http://purl.org/dc/terms/">
  <dc:title>Sample Doc</dc:title>
  <dc:creator>Test Author</dc:creator>
  <dcterms:modified xsi:type="dcterms:W3CDTF" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">2026-04-26T00:00:00Z</dcterms:modified>
</cp:coreProperties>
"""

_DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Sample Doc</w:t></w:r></w:p>
    <w:p><w:r><w:t>Body paragraph.</w:t></w:r></w:p>
  </w:body>
</w:document>
"""


def _build_docx(out_path: Path, app_xml: str) -> None:
    """Synthesize a minimal DOCX with a custom app.xml."""
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("docProps/core.xml", _CORE)
        z.writestr("docProps/app.xml", app_xml)
        z.writestr("word/document.xml", _DOCUMENT)


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
    # v1.0.2: existing fixture has Company="Test Org" but no Application
    # field, so produced_by stays None and is omitted.
    assert "produced_by" not in fm


def test_docx_application_only_routes_to_produced_by(
    tmp_path, tmp_output_dir, monkeypatch
):
    """When Application is software and Company is absent, produced_by populated."""
    monkeypatch.setattr(
        "any2md.converters.docx.has_docling", lambda: False
    )
    docx = tmp_path / "app_only.docx"
    _build_docx(
        docx,
        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Application>Microsoft Office Word</Application>
</Properties>
""",
    )
    ok = convert_docx(docx, tmp_output_dir, options=PipelineOptions(), force=True)
    assert ok
    out = next(tmp_output_dir.glob("*.md")).read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    # Application is software → org cleared, produced_by populated.
    assert fm["organization"] == ""
    assert fm["produced_by"] == "Microsoft Office Word"


def test_docx_company_and_application_company_wins(
    tmp_path, tmp_output_dir, monkeypatch
):
    """Company is the real org; Application becomes produced_by."""
    monkeypatch.setattr(
        "any2md.converters.docx.has_docling", lambda: False
    )
    docx = tmp_path / "company_and_app.docx"
    _build_docx(
        docx,
        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Company>Acme Corp</Company>
  <Application>Microsoft Office Word</Application>
</Properties>
""",
    )
    ok = convert_docx(docx, tmp_output_dir, options=PipelineOptions(), force=True)
    assert ok
    out = next(tmp_output_dir.glob("*.md")).read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    assert fm["organization"] == "Acme Corp"
    assert fm["produced_by"] == "Microsoft Office Word"


def test_docx_application_real_org_routes_to_organization(
    tmp_path, tmp_output_dir, monkeypatch
):
    """When Company absent and Application looks like a real org name."""
    monkeypatch.setattr(
        "any2md.converters.docx.has_docling", lambda: False
    )
    docx = tmp_path / "app_real_org.docx"
    _build_docx(
        docx,
        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Application>Acme Internal Tooling</Application>
</Properties>
""",
    )
    ok = convert_docx(docx, tmp_output_dir, options=PipelineOptions(), force=True)
    assert ok
    out = next(tmp_output_dir.glob("*.md")).read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    # filter_organization treats unknown strings as a real organization.
    assert fm["organization"] == "Acme Internal Tooling"
    assert "produced_by" not in fm
