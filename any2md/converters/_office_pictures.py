"""Pictures in Docling documents: PDF, Word, PowerPoint, and Excel.

Docling adds every picture to the DoclingDocument, but its Markdown
writes each one as a bare ``<!-- image -->`` placeholder that
structured-lane S1 deletes. This module turns each picture into the
Markdown image S1 expects, ``![text](link)``, so S1 writes
``*Figure: text*`` and keeps the link only under ``--save-images``.
The DOCX mammoth lane builds the same images through mammoth's hooks,
so every lane follows one rule.

The figure text is the picture's Docling caption (a PDF caption or a
chart title), else a Word Caption paragraph right after the picture,
else the description Docling recorded (an image placed in a cell), else
the alt text the author typed. Docling drops that alt text, so this
module reads it straight from the OOXML package and pairs it with the
Docling picture: by position for PowerPoint and Excel, by document
order for Word.

The position key copies the arithmetic Docling uses for a picture's
provenance box: slide EMUs mapped through every enclosing group's
transform and clamped to the slide for PowerPoint, and the anchor's
cell range for Excel. A picture this module cannot place keeps no alt
text, which leaves its figure line to the caption or drops it.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from typing import Any, Iterator

from defusedxml.ElementTree import ParseError, fromstring

from any2md import _logging
from any2md._logging import safe_oneline
from any2md._image_files import ImageWriter
from any2md._safe_open import SourceFile
from any2md.pipeline.structured import NO_IMAGE_LINK

# Written in place of each picture, carrying the picture's self_ref
# ("#/pictures/3"), so each token is filled with its own picture's
# Markdown. A comment, so the Markdown stays valid if a token is ever
# left unfilled, and a name no document text produces.
_TOKEN_PREFIX = "<!-- any2md-picture "
_TOKEN_RE = re.compile(r"<!-- any2md-picture (#/[A-Za-z0-9_/]+) -->")


def picture_token(ref: str) -> str:
    """The token that stands for the picture whose self_ref is ``ref``."""
    return f"{_TOKEN_PREFIX}{ref} -->"


def has_picture_token(md: str) -> bool:
    return _TOKEN_RE.search(md) is not None


_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"

# One XML part is read at most this large. Slide and drawing parts are
# rarely past a few hundred KiB. The zip guard has already capped the
# whole archive, and this cap keeps one oversized part from costing
# more than the alt text is worth.
_MAX_PART_BYTES = 16 * 1024 * 1024

# Docling's coordinates pass through float scaling for grouped shapes,
# so a match allows a few EMUs of rounding. An EMU is 1/914400 inch.
_EMU_TOLERANCE = 2.0

Box = tuple[float, float, float, float]


@dataclass
class WordPicture:
    """One picture of a Word document, in document order.

    ``caption`` is the text of a Caption-style paragraph right after the
    paragraph that holds the picture, the place Word's Insert Caption
    puts it by default.
    """

    alt: str = ""
    caption: str = ""


@dataclass
class AltTexts:
    """Alt text found in a package.

    PowerPoint and Excel entries sit in ``by_page`` as (box, text) pairs
    in package order. A Word document has no positions Docling keeps, so
    its pictures sit in ``in_order``, one per drawing in document order.
    """

    by_page: dict[Any, list[tuple[Box, str]]] = field(default_factory=dict)
    tolerance: float = _EMU_TOLERANCE
    in_order: list[WordPicture] | None = None
    # Set when the package could not be read, for the run's warnings.
    warning: str | None = None

    def add(self, page: Any, box: Box, text: str) -> None:
        self.by_page.setdefault(page, []).append((box, text))

    def take(self, page: Any, box: Box) -> str:
        """Return and remove the first entry on ``page`` at ``box``, else ""."""
        entries = self.by_page.get(page, [])
        for i, (candidate, text) in enumerate(entries):
            if all(abs(a - b) <= self.tolerance for a, b in zip(candidate, box)):
                del entries[i]
                return text
        return ""


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _read_xml(z: zipfile.ZipFile, name: str) -> Any | None:
    """Parse one package part, or None when it is missing or unreadable."""
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > _MAX_PART_BYTES:
        return None
    try:
        with z.open(info) as f:
            return fromstring(f.read())
    except (ParseError, OSError, zipfile.BadZipFile, ValueError):
        return None


def _rels(z: zipfile.ZipFile, part: str) -> dict[str, str]:
    """Map each relationship id of ``part`` to its resolved part name."""
    base, name = posixpath.split(part)
    root = _read_xml(z, posixpath.join(base, "_rels", name + ".rels"))
    if root is None:
        return {}
    out = {}
    for rel in root.iter(_q(_PKG, "Relationship")):
        target = rel.get("Target") or ""
        if rel.get("TargetMode") == "External" or not target:
            continue
        if target.startswith("/"):
            resolved = target.lstrip("/")
        else:
            resolved = posixpath.normpath(posixpath.join(base, target))
        out[rel.get("Id") or ""] = resolved
    return out


def _alt_of(nv_props: Any) -> str:
    """The alt text on a ``cNvPr`` element: its description, else its title."""
    if nv_props is None:
        return ""
    return " ".join((nv_props.get("descr") or nv_props.get("title") or "").split())


def _int(element: Any, attr: str) -> int | None:
    try:
        return int(element.get(attr))
    except (TypeError, ValueError):
        return None


def _group_transform(group: Any) -> tuple[list[int], Any] | None:
    """Return a group's off, ext, chOff, and chExt numbers and its xfrm."""
    xfrm = group.find(f"{_q(_P, 'grpSpPr')}/{_q(_A, 'xfrm')}")
    if xfrm is None:
        return None
    parts = [xfrm.find(_q(_A, n)) for n in ("off", "ext", "chOff", "chExt")]
    numbers: list[int] = []
    for part, (ax, ay) in zip(parts, [("x", "y"), ("cx", "cy")] * 2):
        if part is None:
            return None
        x, y = _int(part, ax), _int(part, ay)
        if x is None or y is None:
            return None
        numbers += [x, y]
    return numbers, xfrm


def _to_slide(box: Box, groups: list[Any]) -> Box:
    """Map a box in a grouped shape's space to slide space, innermost group first.

    Mirrors Docling's ``_to_slide_coordinates`` so the result equals the
    provenance box Docling records for the same shape.
    """
    left, top, right, bottom = box
    for group in reversed(groups):
        transform = _group_transform(group)
        if transform is None:
            continue
        (off_x, off_y, ext_x, ext_y, ch_x, ch_y, ch_cx, ch_cy), xfrm = transform
        scale_x = ext_x / ch_cx if ch_cx else 1.0
        scale_y = ext_y / ch_cy if ch_cy else 1.0
        left = off_x + (left - ch_x) * scale_x
        right = off_x + (right - ch_x) * scale_x
        top = off_y + (top - ch_y) * scale_y
        bottom = off_y + (bottom - ch_y) * scale_y
        if xfrm.get("flipH") in ("1", "true"):
            left, right = 2 * off_x + ext_x - right, 2 * off_x + ext_x - left
        if xfrm.get("flipV") in ("1", "true"):
            top, bottom = 2 * off_y + ext_y - bottom, 2 * off_y + ext_y - top
    return left, top, right, bottom


def _clamp(box: Box, width: float, height: float) -> Box:
    """Clamp like docling-core does when it validates a provenance box."""
    left, top, right, bottom = box

    def c(v: float, hi: float) -> float:
        return min(max(v, 0.0), hi)

    return c(left, width), c(top, height), c(right, width), c(bottom, height)


def _shape_box(xfrm: Any) -> Box | None:
    if xfrm is None:
        return None
    off, ext = xfrm.find(_q(_A, "off")), xfrm.find(_q(_A, "ext"))
    if off is None or ext is None:
        return None
    x, y, cx, cy = _int(off, "x"), _int(off, "y"), _int(ext, "cx"), _int(ext, "cy")
    if None in (x, y, cx, cy):
        return None
    return x, y, x + cx, y + cy  # type: ignore[operator]


def _picture_shapes(tree: Any, groups: list[Any]) -> Iterator[tuple[Any, list[Any]]]:
    """Yield (shape, enclosing groups) for each shape Docling may record as a picture."""
    for child in tree:
        if child.tag == _q(_P, "grpSp"):
            yield from _picture_shapes(child, [*groups, child])
        elif child.tag in (_q(_P, "pic"), _q(_P, "graphicFrame"), _q(_P, "sp")):
            yield child, groups


def _pptx_shape_entry(shape: Any) -> tuple[str, Any] | None:
    """Return (alt text, xfrm) for a picture-bearing shape, else None."""
    if shape.tag == _q(_P, "pic"):
        nv = shape.find(f"{_q(_P, 'nvPicPr')}/{_q(_P, 'cNvPr')}")
        xfrm = shape.find(f"{_q(_P, 'spPr')}/{_q(_A, 'xfrm')}")
    elif shape.tag == _q(_P, "graphicFrame"):
        # Charts and other graphic frames: Docling records a chart as a picture.
        nv = shape.find(f"{_q(_P, 'nvGraphicFramePr')}/{_q(_P, 'cNvPr')}")
        xfrm = shape.find(_q(_P, "xfrm"))
    else:
        # An ordinary shape counts only when a picture fills it.
        if shape.find(f"{_q(_P, 'spPr')}/{_q(_A, 'blipFill')}") is None:
            return None
        nv = shape.find(f"{_q(_P, 'nvSpPr')}/{_q(_P, 'cNvPr')}")
        xfrm = shape.find(f"{_q(_P, 'spPr')}/{_q(_A, 'xfrm')}")
    alt = _alt_of(nv)
    return (alt, xfrm) if alt else None


def _pptx_alt_texts(z: zipfile.ZipFile) -> AltTexts:
    out = AltTexts()
    pres_part = "ppt/presentation.xml"
    pres = _read_xml(z, pres_part)
    if pres is None:
        return out
    size = pres.find(_q(_P, "sldSz"))
    width = _int(size, "cx") if size is not None else None
    height = _int(size, "cy") if size is not None else None
    rels = _rels(z, pres_part)
    slide_ids = pres.find(_q(_P, "sldIdLst"))
    if slide_ids is None:
        return out
    for page_no, sld in enumerate(slide_ids.iter(_q(_P, "sldId")), start=1):
        part = rels.get(sld.get(_q(_R, "id")) or "")
        slide = _read_xml(z, part) if part else None
        tree = (
            None
            if slide is None
            else slide.find(f"{_q(_P, 'cSld')}/{_q(_P, 'spTree')}")
        )
        if tree is None:
            continue
        for shape, groups in _picture_shapes(tree, []):
            entry = _pptx_shape_entry(shape)
            if entry is None:
                continue
            alt, xfrm = entry
            box = _shape_box(xfrm)
            if box is None:
                # A placeholder picture without its own transform takes its
                # position from the layout, which this reader does not follow.
                continue
            box = _to_slide(box, groups)
            if width and height:
                box = _clamp(box, width, height)
            out.add(page_no, box, alt)
    return out


def _anchor_box(anchor: Any) -> Box | None:
    """The (left col, top row, right col, bottom row) box Docling records."""
    start = anchor.find(_q(_XDR, "from"))
    if start is None:
        return None
    col = _int_text(start, "col")
    row = _int_text(start, "row")
    if col is None or row is None:
        return None
    if anchor.tag == _q(_XDR, "twoCellAnchor"):
        end = anchor.find(_q(_XDR, "to"))
        end_col = _int_text(end, "col") if end is not None else None
        end_row = _int_text(end, "row") if end is not None else None
        if end_col is None or end_row is None:
            return None
        return col, row, end_col + 1, end_row + 1
    return col, row, col + 1, row + 1


def _int_text(element: Any, tag: str) -> int | None:
    child = element.find(_q(_XDR, tag))
    try:
        return int((child.text or "").strip()) if child is not None else None
    except ValueError:
        return None


def _xlsx_alt_texts(z: zipfile.ZipFile) -> AltTexts:
    # Excel boxes are whole cells, so any difference is a different picture.
    out = AltTexts(tolerance=0.0)
    book_part = "xl/workbook.xml"
    book = _read_xml(z, book_part)
    if book is None:
        return out
    rels = _rels(z, book_part)
    sheets = book.find(_q(_S, "sheets"))
    if sheets is None:
        return out
    for sheet in sheets.iter(_q(_S, "sheet")):
        name = sheet.get("name") or ""
        part = rels.get(sheet.get(_q(_R, "id")) or "")
        ws = _read_xml(z, part) if part else None
        if ws is None:
            continue
        sheet_rels = _rels(z, part)
        for drawing_ref in ws.iter(_q(_S, "drawing")):
            drawing_part = sheet_rels.get(drawing_ref.get(_q(_R, "id")) or "")
            drawing = _read_xml(z, drawing_part) if drawing_part else None
            if drawing is None:
                continue
            for anchor in drawing:
                if anchor.tag not in (
                    _q(_XDR, "twoCellAnchor"),
                    _q(_XDR, "oneCellAnchor"),
                ):
                    continue
                nv = anchor.find(
                    f"{_q(_XDR, 'pic')}/{_q(_XDR, 'nvPicPr')}/{_q(_XDR, 'cNvPr')}"
                )
                alt = _alt_of(nv)
                box = _anchor_box(anchor)
                if alt and box is not None:
                    out.add(name, box, alt)
    return out


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_V = "urn:schemas-microsoft-com:vml"
_O = "urn:schemas-microsoft-com:office:office"
_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def _caption_style_ids(z: zipfile.ZipFile) -> set[str]:
    """Paragraph style ids named "caption" (Word's built-in name), or "Caption"."""
    ids = {"Caption"}
    styles = _read_xml(z, "word/styles.xml")
    if styles is None:
        return ids
    for style in styles.iter(_q(_W, "style")):
        name = style.find(_q(_W, "name"))
        if name is not None and (name.get(_q(_W, "val")) or "").casefold() == "caption":
            ids.add(style.get(_q(_W, "styleId")) or "")
    return ids


def _paragraph_text(paragraph: Any) -> str:
    return " ".join("".join(t.text or "" for t in paragraph.iter(_q(_W, "t"))).split())


def _paragraph_style(paragraph: Any) -> str:
    style = paragraph.find(f"{_q(_W, 'pPr')}/{_q(_W, 'pStyle')}")
    return (style.get(_q(_W, "val")) or "") if style is not None else ""


def _picture_stands_alone(paragraph: Any) -> bool:
    """True when the paragraph holds no text besides its picture.

    A Caption paragraph under a picture that sits in a line of text
    describes that text, not the picture.
    """
    return not _paragraph_text(paragraph)


def _is_table(element: Any) -> bool:
    """A Caption paragraph right above a table is the table's caption."""
    return element is not None and element.tag == _q(_W, "tbl")


def _is_picture_element(element: Any) -> bool:
    """A DrawingML drawing or a VML image: what Docling reads as a picture."""
    return element.tag == _q(_W, "drawing") or element.tag == _q(_V, "imagedata")


def _word_alt(element: Any) -> str:
    """Alt text the way mammoth reads it: description, else title."""
    if element.tag == _q(_W, "drawing"):
        props = element.find(f".//{_q(_WP, 'docPr')}")
        if props is None:
            return ""
        descr = props.get("descr") or ""
        return " ".join((descr if descr.strip() else props.get("title") or "").split())
    return " ".join((element.get(_q(_O, "title")) or "").split())


def _docx_alt_texts(z: zipfile.ZipFile) -> AltTexts:
    document = _read_xml(z, "word/document.xml")
    body = None if document is None else document.find(_q(_W, "body"))
    if body is None:
        return AltTexts(in_order=[])
    caption_ids = _caption_style_ids(z)

    # One walk in document order. It notes each picture with the nearest
    # paragraph that holds it, and where every element sits among its
    # parent's children, so each check below is a lookup, never a scan.
    # A paragraph inside a text box is the nearest paragraph of the
    # pictures it holds, so they are not counted for the outer one.
    # Word saves a drawing as mc:AlternateContent with a DrawingML
    # mc:Choice and a VML mc:Fallback copy of the same picture. Docling
    # counts one picture there, so the walk skips every Fallback subtree.
    # Counting both would make the totals differ, and a mismatch turns
    # alt text and captions off for the whole document.
    pictures: list[tuple[Any, Any]] = []
    held: dict[int, int] = {}
    position: dict[int, tuple[list[Any], int]] = {}
    stack: list[tuple[Any, Any]] = [(body, None)]
    while stack:
        element, paragraph = stack.pop()
        if element.tag == _q(_MC, "Fallback"):
            continue
        if element.tag == _q(_W, "p"):
            paragraph = element
        elif paragraph is not None and _is_picture_element(element):
            pictures.append((element, paragraph))
            held[id(paragraph)] = held.get(id(paragraph), 0) + 1
        children = list(element)
        for i, child in enumerate(children):
            position[id(child)] = (children, i)
        stack.extend((child, paragraph) for child in reversed(children))

    captions: dict[int, str] = {}
    entries = []
    for element, paragraph in pictures:
        key = id(paragraph)
        if key not in captions:
            captions[key] = (
                _caption_after(paragraph, position, caption_ids)
                if held[key] == 1
                else ""
            )
        entries.append(WordPicture(alt=_word_alt(element), caption=captions[key]))
    return AltTexts(in_order=entries)


def _caption_after(
    paragraph: Any, position: dict[int, tuple[list[Any], int]], caption_ids: set[str]
) -> str:
    """The Caption paragraph right after ``paragraph``, when it names its picture."""
    siblings, index = position[id(paragraph)]
    following = siblings[index + 1] if index + 1 < len(siblings) else None
    after = siblings[index + 2] if index + 2 < len(siblings) else None
    if (
        _picture_stands_alone(paragraph)
        and following is not None
        and following.tag == _q(_W, "p")
        and _paragraph_style(following) in caption_ids
        and not _is_table(after)
    ):
        return _paragraph_text(following)
    return ""


_UNREADABLE = (
    OSError,
    zipfile.BadZipFile,
    ValueError,
    RuntimeError,
    NotImplementedError,
    zlib.error,
    EOFError,
    KeyError,
)


def read_alt_texts(src: SourceFile, fmt: str) -> AltTexts:
    """Read the picture alt text in ``src``. An unreadable package gives none.

    Alt text adds to what Docling already extracted,
    so a part this reader cannot parse costs that alt text only, never
    the file. ``warning`` then names what failed, for the run's warnings.
    """
    try:
        with src.open_binary() as fh, zipfile.ZipFile(fh) as z:
            if fmt == "pptx":
                return _pptx_alt_texts(z)
            if fmt == "docx":
                return _docx_alt_texts(z)
            return _xlsx_alt_texts(z)
    except _UNREADABLE as e:
        # zipfile and zlib raise these on a corrupt member (a bad deflate
        # stream, a truncated entry, a compression method it lacks).
        return AltTexts(
            warning=f"alt text: could not read the package: {safe_oneline(str(e))}"
        )


def is_picture(item: Any) -> bool:
    """True for a Docling picture item, charts included."""
    label = getattr(item, "label", None)
    return str(getattr(label, "value", label)) in ("picture", "chart")


def _caption(doc: Any, item: Any) -> str:
    if not getattr(item, "captions", None):
        return ""
    try:
        return " ".join(item.caption_text(doc).split())
    except (AttributeError, IndexError, KeyError, ValueError):
        return ""


def _description(item: Any) -> str:
    description = getattr(getattr(item, "meta", None), "description", None)
    return " ".join((getattr(description, "text", "") or "").split())


def _position_key(doc: Any, item: Any, fmt: str) -> tuple[Any, Box] | None:
    """Return the (page, box) key ``AltTexts`` files this picture under."""
    prov = getattr(item, "prov", None)
    if not prov:
        return None
    bbox = prov[0].bbox
    box = (bbox.l, bbox.t, bbox.r, bbox.b)
    if fmt == "pptx":
        return prov[0].page_no, box
    # Sheets pair with pictures by name, which does not depend on how
    # Docling numbers pages for hidden sheets or chart sheets.
    try:
        sheet = item.parent.resolve(doc)
    except (AttributeError, IndexError, KeyError, ValueError):
        return None
    return getattr(sheet, "name", None), box


def alt_markdown(text: str) -> str:
    """Escape figure text for the alt part of ``![...](...)``.

    S1's image pattern stops the alt text at an unescaped bracket.
    """
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _save_picture(doc: Any, item: Any, writer: ImageWriter, number: int) -> str | None:
    """Save the picture as ``imgN.png``. Returns its link, or None without data."""
    try:
        pil_image = item.get_image(doc)
    except Exception as e:  # noqa: BLE001 -- one bad picture must not fail the file
        _logging.warn(f"failed to read image img{number}: {e}")
        return None
    if pil_image is None:
        return None
    return writer.write_png(number, pil_image)


def _content_layer(name: str) -> Any | None:
    """docling-core's ContentLayer member ``name``, or None without Docling."""
    try:
        from docling_core.types.doc import ContentLayer
    except ImportError:
        return None
    return getattr(ContentLayer, name, None)


def _word_pictures(doc: Any, alt_texts: AltTexts) -> dict[int, WordPicture]:
    """Pair Word pictures with Docling's picture items by document order.

    Docling files a tiny or blank image as an invisible spacer, but it
    still has a drawing in ``document.xml``, so the count covers the body
    and invisible layers. Header and footer pictures live in other parts
    and stay out. Any other mismatch (a drawing Docling splits into
    several pictures, a text box it reads as text) breaks the pairing,
    so the pairing is used only when both counts agree.
    """
    if not alt_texts.in_order:
        return {}
    layers = {_content_layer("BODY"), _content_layer("INVISIBLE")} - {None}
    kwargs = {"included_content_layers": layers} if layers else {}
    pictures = [
        item for item, _level in doc.iterate_items(**kwargs) if is_picture(item)
    ]
    if len(pictures) != len(alt_texts.in_order):
        return {}
    return {id(p): entry for p, entry in zip(pictures, alt_texts.in_order)}


def _hide_caption_paragraph(item: Any, caption: str) -> None:
    """Keep a Word caption paragraph out of the body once it is a figure line.

    Docling does not link a Word caption to its picture and writes it as
    the paragraph right after the picture. Moving that one item to the
    invisible layer stops the caption from showing twice.
    """
    if item is None or " ".join((getattr(item, "text", "") or "").split()) != caption:
        return
    invisible = _content_layer("INVISIBLE")
    if invisible is not None:
        item.content_layer = invisible


def prepare_pictures(
    doc: Any,
    fmt: str,
    alt_texts: AltTexts,
    writer: ImageWriter | None,
) -> dict[str, str]:
    """Return the Markdown that stands in for each picture, keyed by self_ref.

    With a ``writer`` (``--save-images``) each picture is saved through
    it as ``imgN.png``, numbered in document order, and linked. The
    caller runs ``writer.commit(markdown)`` once the final Markdown is
    written. Captions move into the figure text, and each
    picture's caption list is cleared so Docling does not write the
    caption a second time as a plain paragraph.

    The text is, in order: the Docling caption, a Word Caption paragraph
    right after the picture, the Docling description, the alt text.
    """
    body_items = [item for item, _level in doc.iterate_items()]
    following = {id(a): b for a, b in zip(body_items, body_items[1:])}
    word = _word_pictures(doc, alt_texts)
    figures: dict[str, str] = {}
    number = 0
    for item in body_items:
        if not is_picture(item):
            continue
        entry = word.get(id(item))
        text = _caption(doc, item)
        if not text and entry is not None and entry.caption:
            text = entry.caption
            _hide_caption_paragraph(following.get(id(item)), entry.caption)
        text = text or _description(item)
        if not text and entry is not None:
            text = entry.alt
        elif not text and fmt in ("pptx", "xlsx"):
            key = _position_key(doc, item, fmt)
            text = alt_texts.take(*key) if key is not None else ""
        if getattr(item, "captions", None):
            item.captions = []
        link = None
        if writer is not None:
            number += 1
            link = _save_picture(doc, item, writer, number)
        if text or link:
            figures[item.self_ref] = f"![{alt_markdown(text)}]({link or NO_IMAGE_LINK})"
        else:
            figures[item.self_ref] = ""
    return figures


def fill_pictures(md: str, figures: dict[str, str]) -> str:
    """Replace each picture token in ``md`` with its own picture's Markdown.

    Each token names its picture's self_ref, so a picture that Docling
    leaves out of the Markdown (or writes twice) cannot shift any other
    picture's figure line onto the wrong place. A token for a picture
    with no entry is removed.
    """
    return _TOKEN_RE.sub(lambda m: figures.get(m.group(1), ""), md)


class MarkdownExport:
    """Docling's Markdown for a document or one of its subtrees.

    Each picture is written as its token. Otherwise the parameters match
    ``DoclingDocument.export_to_markdown``'s defaults. One serializer is
    kept per label set: docling-core builds its filter of excluded items
    by walking the whole document once per serializer and parameter set,
    so reusing it keeps a deck of N slides at one walk per label set
    instead of one per slide, which was quadratic.

    A document that is not a DoclingDocument (a stand-in in the unit
    tests) exports itself and writes the tokens on its own.
    """

    def __init__(self, doc: Any) -> None:
        self._doc = doc
        self._serializers: dict[frozenset[Any] | None, Any] = {}

    def __call__(self, *, labels: set[Any] | None = None, item: Any = None) -> str:
        if not _is_docling_document(self._doc):
            kwargs = {"labels": labels, "item": item}
            return self._doc.export_to_markdown(
                **{k: v for k, v in kwargs.items() if v is not None}
            )
        key = frozenset(labels) if labels is not None else None
        serializer = self._serializers.get(key)
        if serializer is None:
            serializer = _token_serializer(self._doc, labels)
            self._serializers[key] = serializer
        return serializer.serialize(item=item).text


def export_markdown(doc: Any, *, labels: set[Any] | None = None) -> str:
    """Docling's Markdown for the whole of ``doc``, with picture tokens."""
    return MarkdownExport(doc)(labels=labels)


def _is_docling_document(doc: Any) -> bool:
    try:
        from docling_core.types.doc.document import DoclingDocument
    except ImportError:
        return False
    return isinstance(doc, DoclingDocument)


def _token_serializer(doc: Any, labels: set[Any] | None) -> Any:
    from docling_core.transforms.serializer.markdown import (
        MarkdownDocSerializer,
        MarkdownParams,
    )
    from docling_core.types.doc.document import DOCUMENT_TOKENS_EXPORT_LABELS

    return MarkdownDocSerializer(
        doc=doc,
        picture_serializer=_token_picture_serializer(),
        params=MarkdownParams(
            labels=labels if labels is not None else DOCUMENT_TOKENS_EXPORT_LABELS
        ),
    )


def _token_picture_serializer() -> Any:
    """A Markdown picture serializer that writes each picture's token."""
    from docling_core.transforms.serializer.common import create_ser_result
    from docling_core.transforms.serializer.markdown import MarkdownPictureSerializer

    class _TokenPictureSerializer(MarkdownPictureSerializer):
        def _serialize_image_part(
            self, item, doc, image_mode, image_placeholder, **kwargs
        ):
            return create_ser_result(
                text=picture_token(item.self_ref), span_source=item
            )

    return _TokenPictureSerializer()
