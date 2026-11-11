"""Build tiny PowerPoint and Excel files from raw OOXML parts.

Docling's own test data is not available offline, and committing binary
fixtures hides their content from review. These builders write the
smallest packages that python-pptx and openpyxl (the libraries behind
Docling's MS PowerPoint and MS Excel backends) accept, so the tests can
read exactly what each file holds.
"""

from __future__ import annotations

import struct
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

_PKG_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_DOC_RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PML = "http://schemas.openxmlformats.org/presentationml/2006/main"
_DML = "http://schemas.openxmlformats.org/drawingml/2006/main"
_SML = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"

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
        '<Default Extension="png" ContentType="image/png"/>'
        f"{body}</Types>"
    )


def tiny_png() -> bytes:
    """A valid 8x8 RGB PNG, built by hand so no imaging library is needed.

    Docling's Word backend files any image of 25 pixels or less, or one
    that is pure white, as an invisible layout spacer, so the image is
    larger than that and colored.
    """

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)
    rows = b"".join(b"\x00" + b"\x80\x20\x20" * 8 for _ in range(8))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


@dataclass
class Picture:
    """One picture on a slide.

    ``box`` is (x, y, cx, cy) in EMUs. With ``grouped`` set the picture
    sits inside a group shape that doubles its size and moves it, so its
    slide position differs from its own transform.
    """

    alt: str = ""
    box: tuple[int, int, int, int] = (457200, 0, 914400, 914400)
    grouped: bool = False


@dataclass
class Slide:
    """One slide. Each part with a ``*_y`` offset gets that vertical position.

    ``title`` is a list of paragraphs in the title placeholder.
    ``title_type`` is the placeholder type ("title" or "ctrTitle").
    A part left at None is left off the slide.
    """

    title: list[str] | None = None
    title_type: str = "title"
    title_y: int | None = 1828800
    body: str | None = None
    body_y: int | None = 3657600
    pictures: list[Picture] = field(default_factory=list)


def _xfrm(x: int, y: int, cx: int, cy: int) -> str:
    return f'<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'


def _text_shape(
    shape_id: int,
    name: str,
    paragraphs: list[str],
    placeholder: str | None,
    y: int | None = None,
) -> str:
    ph = (
        f'<p:nvPr><p:ph type="{placeholder}"/></p:nvPr>' if placeholder else "<p:nvPr/>"
    )
    sp_pr = (
        f"<p:spPr>{_xfrm(457200, y, 8229600, 914400)}</p:spPr>"
        if y is not None
        else "<p:spPr/>"
    )
    paras = "".join(
        f"<a:p><a:r><a:t>{escape(text)}</a:t></a:r></a:p>" for text in paragraphs
    )
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="{name}"/>'
        f"<p:cNvSpPr/>{ph}</p:nvSpPr>{sp_pr}"
        f"<p:txBody><a:bodyPr/>{paras}</p:txBody></p:sp>"
    )


def _picture_shape(shape_id: int, rid: str, pic: Picture) -> str:
    descr = f' descr="{escape(pic.alt, {chr(34): "&quot;"})}"' if pic.alt else ""
    shape = (
        f'<p:pic><p:nvPicPr><p:cNvPr id="{shape_id}" name="Picture {shape_id}"{descr}/>'
        "<p:cNvPicPr/><p:nvPr/></p:nvPicPr>"
        f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch>'
        f"</p:blipFill><p:spPr>{_xfrm(*pic.box)}"
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
    )
    if not pic.grouped:
        return shape
    x, y, cx, cy = pic.box
    # The group maps its child space (chOff/chExt) onto a box twice as large,
    # moved one inch right, the way a resized group looks in PowerPoint.
    group_xfrm = (
        f'<a:xfrm><a:off x="{x + 914400}" y="{y}"/><a:ext cx="{cx * 2}" cy="{cy * 2}"/>'
        f'<a:chOff x="{x}" y="{y}"/><a:chExt cx="{cx}" cy="{cy}"/></a:xfrm>'
    )
    return (
        f'<p:grpSp><p:nvGrpSpPr><p:cNvPr id="{shape_id + 100}" name="Group"/>'
        f"<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr>{group_xfrm}</p:grpSpPr>"
        f"{shape}</p:grpSp>"
    )


def _slide_xml(slide: Slide) -> str:
    shapes = []
    for i, pic in enumerate(slide.pictures):
        shapes.append(_picture_shape(10 + i, f"rIdImg{i + 1}", pic))
    if slide.title is not None:
        shapes.append(
            _text_shape(2, "Title 1", slide.title, slide.title_type, slide.title_y)
        )
    if slide.body is not None:
        shapes.append(_text_shape(3, "Content 2", [slide.body], None, slide.body_y))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sld xmlns:p="{_PML}" xmlns:a="{_DML}" xmlns:r="{_DOC_RELS}">'
        "<p:cSld><p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        "<p:grpSpPr/>"
        f"{''.join(shapes)}"
        "</p:spTree></p:cSld></p:sld>"
    )


def _as_slide(spec: Slide | tuple[str | None, str]) -> Slide:
    """Read the short (title, body) form as a slide with unpositioned shapes."""
    if isinstance(spec, Slide):
        return spec
    title, body = spec
    return Slide(title=[title] if title else None, title_y=None, body=body, body_y=None)


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
    path: Path,
    slides: list[Slide | tuple[str | None, str]],
    title: str | None = None,
) -> Path:
    """Write a presentation, one entry per slide.

    A (title, body) tuple gives a slide with one title and one body text,
    neither positioned. A title of None leaves out the title placeholder.
    A ``Slide`` sets positions, title paragraphs, and pictures.
    """
    slides = [_as_slide(s) for s in slides]
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
        image_no = 0
        for i, slide in enumerate(slides, start=1):
            slide_rels = [
                _rel("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml")
            ]
            for k, _ in enumerate(slide.pictures, start=1):
                image_no += 1
                z.writestr(f"ppt/media/image{image_no}.png", tiny_png())
                slide_rels.append(
                    _rel(f"rIdImg{k}", "image", f"../media/image{image_no}.png")
                )
            z.writestr(f"ppt/slides/slide{i}.xml", _slide_xml(slide))
            z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", _rels(*slide_rels))
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


def _sheet_xml(rows: list[list[str]], with_drawing: bool) -> str:
    row_xml = []
    for r, row in enumerate(rows, start=1):
        cells = "".join(
            f'<c r="{_column_letter(c)}{r}" t="inlineStr"><is><t>{escape(v)}</t></is></c>'
            for c, v in enumerate(row)
        )
        row_xml.append(f'<row r="{r}">{cells}</row>')
    drawing = '<drawing r:id="rId1"/>' if with_drawing else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_SML}" xmlns:r="{_DOC_RELS}">'
        f"<sheetData>{''.join(row_xml)}</sheetData>{drawing}</worksheet>"
    )


@dataclass
class SheetPicture:
    """A picture anchored over a cell range: (from col, from row, to col, to row)."""

    alt: str = ""
    cells: tuple[int, int, int, int] = (1, 1, 3, 4)


def _drawing_xml(pictures: list[SheetPicture]) -> str:
    anchors = []
    for i, pic in enumerate(pictures, start=1):
        c1, r1, c2, r2 = pic.cells
        descr = f' descr="{escape(pic.alt, {chr(34): "&quot;"})}"' if pic.alt else ""
        anchors.append(
            "<xdr:twoCellAnchor>"
            f"<xdr:from><xdr:col>{c1}</xdr:col><xdr:colOff>0</xdr:colOff>"
            f"<xdr:row>{r1}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>"
            f"<xdr:to><xdr:col>{c2}</xdr:col><xdr:colOff>0</xdr:colOff>"
            f"<xdr:row>{r2}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>"
            f'<xdr:pic><xdr:nvPicPr><xdr:cNvPr id="{i + 1}" name="Picture {i}"{descr}/>'
            "<xdr:cNvPicPr/></xdr:nvPicPr>"
            f'<xdr:blipFill><a:blip r:embed="rId{i}"/><a:stretch><a:fillRect/>'
            "</a:stretch></xdr:blipFill>"
            f"<xdr:spPr>{_xfrm(0, 0, 914400, 914400)}"
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic>'
            "<xdr:clientData/></xdr:twoCellAnchor>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<xdr:wsDr xmlns:xdr="{_XDR}" xmlns:a="{_DML}" xmlns:r="{_DOC_RELS}">'
        f"{''.join(anchors)}</xdr:wsDr>"
    )


def build_xlsx(
    path: Path,
    sheets: dict[str, list[list[str]]],
    title: str | None = None,
    pictures: dict[str, list[SheetPicture]] | None = None,
) -> Path:
    """Write a workbook with one inline-string table per sheet.

    ``pictures`` maps a sheet name to the pictures drawn on that sheet.
    """
    pictures = pictures or {}
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
        if pictures.get(name):
            overrides.append(
                (
                    f"/xl/drawings/drawing{i}.xml",
                    "application/vnd.openxmlformats-officedocument.drawing+xml",
                )
            )
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
        image_no = 0
        for i, (name, rows) in enumerate(sheets.items(), start=1):
            sheet_pictures = pictures.get(name) or []
            z.writestr(
                f"xl/worksheets/sheet{i}.xml", _sheet_xml(rows, bool(sheet_pictures))
            )
            if not sheet_pictures:
                continue
            z.writestr(
                f"xl/worksheets/_rels/sheet{i}.xml.rels",
                _rels(_rel("rId1", "drawing", f"../drawings/drawing{i}.xml")),
            )
            z.writestr(f"xl/drawings/drawing{i}.xml", _drawing_xml(sheet_pictures))
            drawing_rels = []
            for k, _ in enumerate(sheet_pictures, start=1):
                image_no += 1
                z.writestr(f"xl/media/image{image_no}.png", tiny_png())
                drawing_rels.append(
                    _rel(f"rId{k}", "image", f"../media/image{image_no}.png")
                )
            z.writestr(f"xl/drawings/_rels/drawing{i}.xml.rels", _rels(*drawing_rels))
        if title is not None:
            z.writestr("docProps/core.xml", _CORE_PROPS.format(title=escape(title)))
    return path


_WML = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"

_DOCX_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:styles xmlns:w="{_WML}">'
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
    '<w:name w:val="Normal"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Caption">'
    '<w:name w:val="caption"/><w:basedOn w:val="Normal"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading1">'
    '<w:name w:val="heading 1"/><w:basedOn w:val="Normal"/></w:style>'
    "</w:styles>"
)


@dataclass
class DocPicture:
    """One inline picture in a Word document.

    ``alt`` goes in ``wp:docPr/@descr`` and ``title`` in
    ``wp:docPr/@title``. ``caption`` adds a Caption-style paragraph right
    after the picture. ``linked`` points the picture at an external file
    instead of embedding it, the way "Link to File" does in Word.
    ``text`` puts a text run in the picture's paragraph, before it.
    ``where`` is "body", "cell" (the only cell of a one-cell table), or
    "heading" (a Heading 1 paragraph).
    """

    alt: str = ""
    title: str = ""
    caption: str | None = None
    linked: bool = False
    text: str = ""
    where: str = "body"


@dataclass
class DocTable:
    """A table of plain text cells."""

    rows: list[list[str]]


@dataclass
class DocCaption:
    """A Caption-style paragraph standing on its own."""

    text: str


def _attr(text: str) -> str:
    return escape(text, {'"': "&quot;"})


def _docx_picture(n: int, pic: DocPicture) -> str:
    descr = f' descr="{_attr(pic.alt)}"' if pic.alt else ""
    title = f' title="{_attr(pic.title)}"' if pic.title else ""
    blip = f'r:link="rIdImg{n}"' if pic.linked else f'r:embed="rIdImg{n}"'
    ppr = (
        '<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>' if pic.where == "heading" else ""
    )
    run = (
        f'<w:r><w:t xml:space="preserve">{escape(pic.text)} </w:t></w:r>'
        if pic.text
        else ""
    )
    paragraph = (
        f"<w:p>{ppr}{run}<w:r><w:drawing>"
        '<wp:inline distT="0" distB="0" distL="0" distR="0">'
        '<wp:extent cx="914400" cy="914400"/>'
        f'<wp:docPr id="{n}" name="Picture {n}"{descr}{title}/>'
        f'<a:graphic><a:graphicData uri="{_PIC}"><pic:pic>'
        f'<pic:nvPicPr><pic:cNvPr id="{n}" name="image{n}.png"/><pic:cNvPicPr/>'
        f"</pic:nvPicPr><pic:blipFill><a:blip {blip}/><a:stretch><a:fillRect/>"
        f"</a:stretch></pic:blipFill><pic:spPr>{_xfrm(0, 0, 914400, 914400)}"
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        "</pic:pic></a:graphicData></a:graphic></wp:inline>"
        "</w:drawing></w:r></w:p>"
    )
    if pic.where == "cell":
        return _docx_table([[paragraph]], raw=True)
    return paragraph


def _docx_table(rows: list[list[str]], raw: bool = False) -> str:
    """A table. ``raw`` cells hold paragraph XML instead of plain text."""
    body = "".join(
        "<w:tr>"
        + "".join(
            f"<w:tc>{cell if raw else _docx_paragraph(cell)}</w:tc>" for cell in row
        )
        + "</w:tr>"
        for row in rows
    )
    return f"<w:tbl><w:tblPr/>{body}</w:tbl>"


def _docx_paragraph(text: str, style: str | None = None) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}<w:r><w:t>{escape(text)}</w:t></w:r></w:p>"


def build_docx(
    path: Path,
    blocks: list[str | DocPicture | DocTable | DocCaption],
    title: str | None = None,
) -> Path:
    """Write a Word document: a str is a paragraph, a ``DocPicture`` a
    picture, a ``DocTable`` a table, a ``DocCaption`` a Caption paragraph."""
    body = []
    doc_rels = [_rel("rIdStyles", "styles", "styles.xml")]
    pictures = [b for b in blocks if isinstance(b, DocPicture)]
    number = 0
    for block in blocks:
        if isinstance(block, str):
            body.append(_docx_paragraph(block))
            continue
        if isinstance(block, DocTable):
            body.append(_docx_table(block.rows))
            continue
        if isinstance(block, DocCaption):
            body.append(_docx_paragraph(block.text, "Caption"))
            continue
        number += 1
        body.append(_docx_picture(number, block))
        if block.linked:
            doc_rels.append(
                f'<Relationship Id="rIdImg{number}" Type="{_DOC_RELS}/image" '
                f'Target="file:///nonexistent/linked{number}.png" '
                'TargetMode="External"/>'
            )
        else:
            doc_rels.append(
                _rel(f"rIdImg{number}", "image", f"media/image{number}.png")
            )
        if block.caption is not None:
            body.append(_docx_paragraph(block.caption, "Caption"))
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_WML}" xmlns:wp="{_WP}" xmlns:a="{_DML}" '
        f'xmlns:pic="{_PIC}" xmlns:r="{_DOC_RELS}">'
        f"<w:body>{''.join(body)}</w:body></w:document>"
    )
    wml_ct = "application/vnd.openxmlformats-officedocument.wordprocessingml."
    overrides = [
        ("/word/document.xml", wml_ct + "document.main+xml"),
        ("/word/styles.xml", wml_ct + "styles+xml"),
    ]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _content_types(overrides, title is not None))
        z.writestr("_rels/.rels", _package_rels("word/document.xml", title is not None))
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", _DOCX_STYLES)
        z.writestr("word/_rels/document.xml.rels", _rels(*doc_rels))
        for i, pic in enumerate(pictures, start=1):
            if not pic.linked:
                z.writestr(f"word/media/image{i}.png", tiny_png())
        if title is not None:
            z.writestr("docProps/core.xml", _CORE_PROPS.format(title=escape(title)))
    return path
