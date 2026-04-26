"""Regenerate synthetic test fixtures.

Run from repo root: python tests/fixtures/make_fixtures.py
Outputs deterministic PDFs and DOCX files into tests/fixtures/docs/.
Committed alongside generator so test runs don't require regeneration.
"""

import zipfile
from pathlib import Path
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


FIXTURES = Path(__file__).parent / "docs"


_DOCX_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""

_DOCX_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""

_DOCX_CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/"
                   xmlns:dcterms="http://purl.org/dc/terms/">
  <dc:title>Table Heavy Test Document</dc:title>
  <dc:creator>Test Author</dc:creator>
  <cp:keywords>tables, test, fixture</cp:keywords>
  <dcterms:modified xsi:type="dcterms:W3CDTF" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">2026-04-26T00:00:00Z</dcterms:modified>
</cp:coreProperties>
"""

_DOCX_APP = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Company>Test Org</Company>
</Properties>
"""

_DOCX_DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Table Heavy Test Document</w:t></w:r></w:p>
    <w:p><w:r><w:t>Body paragraph before the table.</w:t></w:r></w:p>
    <w:tbl>
      <w:tblGrid>
        <w:gridCol w:w="4500"/>
        <w:gridCol w:w="4500"/>
      </w:tblGrid>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Header 1</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Header 2</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Cell B</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
    <w:p><w:r><w:t>Body paragraph after the table.</w:t></w:r></w:p>
  </w:body>
</w:document>
"""


def build_table_heavy_docx() -> None:
    out = FIXTURES / "table_heavy.docx"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _DOCX_CONTENT_TYPES)
        z.writestr("_rels/.rels", _DOCX_RELS)
        z.writestr("docProps/core.xml", _DOCX_CORE)
        z.writestr("docProps/app.xml", _DOCX_APP)
        z.writestr("word/document.xml", _DOCX_DOCUMENT)


def build_multi_column_pdf() -> None:
    """Two-column layout, two pages, with a top heading and body text."""
    out = FIXTURES / "multi_column.pdf"
    c = canvas.Canvas(str(out), pagesize=LETTER)
    width, height = LETTER

    # Page 1
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1 * inch, height - 1 * inch, "Multi-Column Test Document")

    body = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
        "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
        "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris."
    )
    c.setFont("Helvetica", 10)
    # Left column
    text_left = c.beginText(1 * inch, height - 1.5 * inch)
    for line in body.split(". "):
        text_left.textLine(line.strip() + ".")
    c.drawText(text_left)
    # Right column
    text_right = c.beginText(4.5 * inch, height - 1.5 * inch)
    for line in body.split(". "):
        text_right.textLine(line.strip() + ".")
    c.drawText(text_right)

    c.showPage()

    # Page 2 — same shape, different content so dedupe doesn't merge them
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1 * inch, height - 1 * inch, "Page 2 Heading")
    c.setFont("Helvetica", 10)
    text_left = c.beginText(1 * inch, height - 1.5 * inch)
    text_left.textLine("Second-page left column content.")
    c.drawText(text_left)
    text_right = c.beginText(4.5 * inch, height - 1.5 * inch)
    text_right.textLine("Second-page right column content.")
    c.drawText(text_right)

    c.save()


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    build_multi_column_pdf()
    build_table_heavy_docx()
    print(f"Wrote {FIXTURES / 'multi_column.pdf'}")
    print(f"Wrote {FIXTURES / 'table_heavy.docx'}")


if __name__ == "__main__":
    main()
