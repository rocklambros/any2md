"""Build tiny PowerPoint and Excel files from raw OOXML parts.

Docling's own test data is not available offline, and committing binary
fixtures hides their content from review. These builders write the
smallest packages that python-pptx and openpyxl (the libraries behind
Docling's MS PowerPoint and MS Excel backends) accept, so the tests can
read exactly what each file holds.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

_PKG_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_DOC_RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PML = "http://schemas.openxmlformats.org/presentationml/2006/main"
_DML = "http://schemas.openxmlformats.org/drawingml/2006/main"
_SML = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

_CORE_PROPS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
  xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{title}</dc:title>
  <dc:creator>Ada Example</dc:creator>
  <dcterms:modified xsi:type="dcterms:W3CDTF">2026-03-15T10:00:00Z</dcterms:modified>
</cp:coreProperties>
"""


def _rel(rid: str, rel_type: str, target: str) -> str:
    return f'<Relationship Id="{rid}" Type="{_DOC_RELS}/{rel_type}" Target="{target}"/>'


def _rels(*entries: str) -> str:
    body = "".join(entries)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_PKG_RELS_NS}">{body}</Relationships>'
    )


def _package_rels(main_part: str, with_core: bool) -> str:
    entries = [_rel("rId1", "officeDocument", main_part)]
    if with_core:
        entries.append(
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/'
            'package/2006/relationships/metadata/core-properties" '
            'Target="docProps/core.xml"/>'
        )
    return _rels(*entries)


def _content_types(overrides: list[tuple[str, str]], with_core: bool) -> str:
    if with_core:
        overrides = [
            *overrides,
            (
                "/docProps/core.xml",
                "application/vnd.openxmlformats-package.core-properties+xml",
            ),
        ]
    body = "".join(
        f'<Override PartName="{name}" ContentType="{ctype}"/>'
        for name, ctype in overrides
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f"{body}</Types>"
    )


def _text_shape(shape_id: int, name: str, text: str, placeholder: str | None) -> str:
    ph = (
        f'<p:nvPr><p:ph type="{placeholder}"/></p:nvPr>' if placeholder else "<p:nvPr/>"
    )
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="{name}"/>'
        f"<p:cNvSpPr/>{ph}</p:nvSpPr><p:spPr/>"
        f"<p:txBody><a:bodyPr/><a:p><a:r><a:t>{escape(text)}</a:t></a:r></a:p>"
        "</p:txBody></p:sp>"
    )


def _slide_xml(title: str | None, body: str) -> str:
    title_shape = _text_shape(2, "Title 1", title, "title") if title else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sld xmlns:p="{_PML}" xmlns:a="{_DML}" xmlns:r="{_DOC_RELS}">'
        "<p:cSld><p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        "<p:grpSpPr/>"
        f"{title_shape}"
        f"{_text_shape(3, 'Content 2', body, None)}"
        "</p:spTree></p:cSld></p:sld>"
    )


_EMPTY_TREE = (
    "<p:cSld><p:spTree>"
    '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
    "<p:grpSpPr/></p:spTree></p:cSld>"
)

# python-pptx resolves a placeholder's inherited properties through the
# slide layout, so a slide with a title placeholder needs a layout part,
# and the layout needs its master.
_LAYOUT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<p:sldLayout xmlns:p="{_PML}" xmlns:a="{_DML}" xmlns:r="{_DOC_RELS}">'
    f"{_EMPTY_TREE}</p:sldLayout>"
)
_MASTER = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<p:sldMaster xmlns:p="{_PML}" xmlns:a="{_DML}" xmlns:r="{_DOC_RELS}">'
    f"{_EMPTY_TREE}"
    '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
    "</p:sldMaster>"
)


def build_pptx(
    path: Path, slides: list[tuple[str | None, str]], title: str | None = None
) -> Path:
    """Write a presentation with one title and one body text per slide.

    A slide title of None leaves out the title placeholder.
    """
    pml_ct = "application/vnd.openxmlformats-officedocument.presentationml."
    overrides = [
        ("/ppt/presentation.xml", pml_ct + "presentation.main+xml"),
        ("/ppt/slideMasters/slideMaster1.xml", pml_ct + "slideMaster+xml"),
        ("/ppt/slideLayouts/slideLayout1.xml", pml_ct + "slideLayout+xml"),
    ]
    sld_ids = []
    # rId1 is the master. Slides take rId2 onward.
    pres_rels = [_rel("rId1", "slideMaster", "slideMasters/slideMaster1.xml")]
    for i, _ in enumerate(slides, start=1):
        overrides.append((f"/ppt/slides/slide{i}.xml", pml_ct + "slide+xml"))
        sld_ids.append(f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>')
        pres_rels.append(_rel(f"rId{i + 1}", "slide", f"slides/slide{i}.xml"))
    presentation = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:presentation xmlns:p="{_PML}" xmlns:a="{_DML}" xmlns:r="{_DOC_RELS}">'
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/>'
        "</p:sldMasterIdLst>"
        f"<p:sldIdLst>{''.join(sld_ids)}</p:sldIdLst>"
        '<p:sldSz cx="9144000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/>'
        "</p:presentation>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _content_types(overrides, title is not None))
        z.writestr(
            "_rels/.rels", _package_rels("ppt/presentation.xml", title is not None)
        )
        z.writestr("ppt/presentation.xml", presentation)
        z.writestr("ppt/_rels/presentation.xml.rels", _rels(*pres_rels))
        z.writestr("ppt/slideMasters/slideMaster1.xml", _MASTER)
        z.writestr(
            "ppt/slideMasters/_rels/slideMaster1.xml.rels",
            _rels(_rel("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml")),
        )
        z.writestr("ppt/slideLayouts/slideLayout1.xml", _LAYOUT)
        z.writestr(
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
            _rels(_rel("rId1", "slideMaster", "../slideMasters/slideMaster1.xml")),
        )
        layout_rel = _rels(
            _rel("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml")
        )
        for i, (slide_title, body) in enumerate(slides, start=1):
            z.writestr(f"ppt/slides/slide{i}.xml", _slide_xml(slide_title, body))
            z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", layout_rel)
        if title is not None:
            z.writestr("docProps/core.xml", _CORE_PROPS.format(title=escape(title)))
    return path


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _sheet_xml(rows: list[list[str]]) -> str:
    row_xml = []
    for r, row in enumerate(rows, start=1):
        cells = "".join(
            f'<c r="{_column_letter(c)}{r}" t="inlineStr"><is><t>{escape(v)}</t></is></c>'
            for c, v in enumerate(row)
        )
        row_xml.append(f'<row r="{r}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_SML}"><sheetData>{"".join(row_xml)}</sheetData></worksheet>'
    )


def build_xlsx(
    path: Path, sheets: dict[str, list[list[str]]], title: str | None = None
) -> Path:
    """Write a workbook with one inline-string table per sheet."""
    sheet_ct = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
    )
    overrides = [
        (
            "/xl/workbook.xml",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        )
    ]
    sheet_entries = []
    wb_rels = []
    for i, name in enumerate(sheets, start=1):
        overrides.append((f"/xl/worksheets/sheet{i}.xml", sheet_ct))
        sheet_entries.append(
            f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
        )
        wb_rels.append(_rel(f"rId{i}", "worksheet", f"worksheets/sheet{i}.xml"))
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{_SML}" xmlns:r="{_DOC_RELS}">'
        f"<sheets>{''.join(sheet_entries)}</sheets></workbook>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _content_types(overrides, title is not None))
        z.writestr("_rels/.rels", _package_rels("xl/workbook.xml", title is not None))
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", _rels(*wb_rels))
        for i, rows in enumerate(sheets.values(), start=1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(rows))
        if title is not None:
            z.writestr("docProps/core.xml", _CORE_PROPS.format(title=escape(title)))
    return path
