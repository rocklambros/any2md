"""Pictures in a PowerPoint deck or an Excel workbook.

Docling's PowerPoint and Excel backends add every picture to the
DoclingDocument, but its Markdown writes each one as a bare
``<!-- image -->`` placeholder that structured-lane S1 deletes. This
module turns each picture into the Markdown image S1 expects,
``![text](link)``, so S1 writes ``*Figure: text*`` and keeps the link
only under ``--save-images``, the same as for any other lane.

The figure text is the picture's Docling caption (a chart title), else
the description Docling recorded (an image placed in a cell), else the
alt text the author typed. Docling drops that alt text (the ``descr``
attribute of the picture's ``cNvPr`` element), so this module reads it
straight from the OOXML package and keys each entry by where the
picture sits, to pair it with the Docling picture at the same place.

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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from defusedxml.ElementTree import ParseError, fromstring

from any2md import _logging
from any2md._safe_open import SourceFile

# Docling writes this in place of each picture. A comment, so the
# Markdown stays valid if a picture is ever left unfilled, and a name no
# document text produces.
PICTURE_TOKEN = "<!-- any2md-picture -->"

# S1 drops the link of a Markdown image unless --save-images is set, so
# a picture with no saved file still needs a syntactically valid one.
_NO_LINK = "#"

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
class AltTexts:
    """Alt text per page, each entry a (box, text) pair in package order."""

    by_page: dict[Any, list[tuple[Box, str]]] = field(default_factory=dict)
    tolerance: float = _EMU_TOLERANCE

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


def read_alt_texts(src: SourceFile, fmt: str) -> AltTexts:
    """Read the picture alt text in ``src``. An unreadable package gives none.

    Alt text is a nice-to-have on top of what Docling already extracted,
    so a part this reader cannot parse costs that alt text only, never
    the file.
    """
    try:
        with src.open_binary() as fh, zipfile.ZipFile(fh) as z:
            if fmt == "pptx":
                return _pptx_alt_texts(z)
            return _xlsx_alt_texts(z)
    except (OSError, zipfile.BadZipFile, ValueError):
        return AltTexts()


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


def _alt_markdown(text: str) -> str:
    """Escape figure text for the alt part of ``![...](...)``.

    S1's image pattern stops the alt text at an unescaped bracket.
    """
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _save_picture(doc: Any, item: Any, image_path: Path) -> bool:
    """Write the picture as a PNG. Returns False when it has no image data."""
    from any2md.converters.pdf import _save_image_safely

    try:
        pil_image = item.get_image(doc)
        if pil_image is None:
            return False
        image_path.parent.mkdir(parents=True, exist_ok=True)
        _save_image_safely(image_path, pil_image)
    except Exception as e:  # noqa: BLE001 -- one bad picture must not fail the file
        _logging.warn(f"failed to save image {image_path.name}: {e}")
        return False
    return True


def prepare_pictures(
    doc: Any,
    fmt: str,
    alt_texts: AltTexts,
    image_dir: Path | None,
    link_dir: str,
) -> dict[int, str]:
    """Return the Markdown that stands in for each picture, keyed by ``id``.

    With ``image_dir`` set (``--save-images``) each picture is written
    there as ``imgN.png``, numbered in document order, and linked as
    ``link_dir/imgN.png``. Captions move into the figure text, and each
    picture's caption list is cleared so Docling does not write the
    caption a second time as a plain paragraph.
    """
    figures: dict[int, str] = {}
    number = 0
    for item, _level in doc.iterate_items():
        if not is_picture(item):
            continue
        text = _caption(doc, item) or _description(item)
        key = _position_key(doc, item, fmt)
        alt = alt_texts.take(*key) if key is not None else ""
        text = text or alt
        if getattr(item, "captions", None):
            item.captions = []
        link = None
        if image_dir is not None:
            number += 1
            name = f"img{number}.png"
            if _save_picture(doc, item, image_dir / name):
                link = f"{link_dir}/{name}"
        if text or link:
            figures[id(item)] = f"![{_alt_markdown(text)}]({link or _NO_LINK})"
        else:
            figures[id(item)] = ""
    return figures


_TOKEN_RE = re.compile(re.escape(PICTURE_TOKEN))


def fill_pictures(
    doc: Any, md: str, figures: dict[int, str], page_no: int | None = None
) -> str:
    """Replace each picture token in ``md`` with that picture's Markdown.

    Docling writes the tokens in the order ``iterate_items`` yields the
    pictures, for the whole document or for one page, so the two line
    up one to one. A token left over (which that order rules out) is
    removed rather than leaking into the output.
    """
    pictures = [
        figures.get(id(item), "")
        for item, _level in doc.iterate_items(page_no=page_no)
        if is_picture(item)
    ]
    queue = iter(pictures)
    return _TOKEN_RE.sub(lambda _m: next(queue, ""), md)
