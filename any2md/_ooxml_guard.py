"""Reject zip bombs before any library reads an OOXML archive.

DOCX, PPTX, and XLSX files are zip archives. mammoth, python-pptx,
openpyxl, and Docling all inflate their parts, and openpyxl builds a
Python object per cell, so a few megabytes of crafted input can demand
gigabytes of memory. ``check_ooxml_archive`` reads the central directory
from the same bytes or handle the converter will use and refuses the
file before any parser runs.

The check trusts the sizes the central directory declares. Python's
``zipfile``, which every one of these libraries reads through, stops
inflating a member at its declared size, so a member that lies about
its size cannot grow past what this check approved.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
import zlib
from typing import Any
from urllib.parse import unquote

from defusedxml.ElementTree import ParseError, fromstring

from any2md._safe_open import SourceFile

# 1 GiB of inflated parts. Real decks, workbooks, and documents rarely
# pass a few hundred MiB, since images are stored at close to their
# compressed size. A fixed ceiling rather than a multiple of
# --max-file-size, because the memory a parser needs depends on the
# inflated XML, not on the size the user allowed on disk.
MAX_TOTAL_UNCOMPRESSED = 1024 * 1024 * 1024

# Office XML compresses about 10 to 30 times, and highly repetitive sheet
# XML can reach 100. Deflate tops out near 1030, which is where bombs
# sit. 250 leaves room for odd but honest files.
MAX_COMPRESSION_RATIO = 250

# Small parts such as styles or shared strings can compress far past
# the ratio limit and still inflate to almost nothing, so the ratio
# test applies only to members larger than this.
RATIO_CHECK_MIN_SIZE = 10 * 1024 * 1024

# Workbooks get tighter limits on their XML, because openpyxl, which
# Docling's Excel backend runs in its default (not read-only) mode, keeps
# a Cell object per cell in memory. A cell costs about 20 to 40 bytes of
# sheet XML (``<c r="A1"><v>1</v></c>`` is 22) and about 250 to 400
# bytes once parsed: the Cell object, its (row, column) key in the
# sheet's cell dict, and the value. Docling then copies each cell into
# its own table model. That puts the expansion near 10 to 20 times the
# XML size, so the 1 GiB archive ceiling alone admits a workbook that
# needs 10 GiB or more. 128 MiB of workbook XML bounds the parse at about
# 2 GiB, and a single part at 96 MiB still holds 3 to 4 million cells,
# far past what a person reads as Markdown. The byte caps also bound the
# cell count, since a cell cannot take fewer than about 20 bytes of XML,
# so the guard does not inflate members to count ``<c>`` elements.
MAX_XLSX_XML_PART = 96 * 1024 * 1024
MAX_XLSX_XML_TOTAL = 128 * 1024 * 1024

# Parts that openpyxl never parses as XML do not count toward the workbook
# caps, so a workbook full of pictures is not refused. A part qualifies
# only when [Content_Types].xml gives it one of these types and no
# relationship of another kind points at it.
_BINARY_CONTENT_TYPES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.oleobject",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.printersettings",
        "application/vnd.ms-office.vbaproject",
        "application/vnd.ms-office.activex",
    }
)
# Relationship kinds (the last segment of the type URI) whose target is
# read as bytes, not parsed as XML. A target of any other kind, such as
# officeDocument, worksheet, sharedStrings, styles, drawing, or chart,
# stays capped whatever content type the archive declares for it.
_BINARY_RELATIONSHIPS = frozenset(
    {
        "image",
        "hdphoto",
        "oleobject",
        "printersettings",
        "vbaproject",
        "activexcontrolbinary",
    }
)

# [Content_Types].xml lists a few dozen entries in an honest workbook. A
# larger one is refused rather than parsed.
MAX_CONTENT_TYPES_BYTES = 1024 * 1024
# Relationship parts read to find what each part is used as. Past either
# limit no part is exempt, which is the safe direction.
MAX_RELS_PART = 1024 * 1024
MAX_RELS_TOTAL = 16 * 1024 * 1024
_RELS_NAME_RE = re.compile(r"(?:^|/)_rels/[^/]*\.rels$", re.IGNORECASE)

# A large workbook or deck holds a few thousand parts. Tens of
# thousands of tiny members only serve to slow the parser.
MAX_MEMBERS = 10_000


class ArchiveRejected(ValueError):
    """An OOXML archive failed the size checks.

    Subclasses ``ValueError`` because every converter already reports
    ``ValueError`` as a per-file failure.
    """


def check_ooxml_archive(src: SourceFile, fmt: str | None = None) -> None:
    """Raise ``ArchiveRejected`` if ``src`` is not a safe-sized zip.

    ``fmt`` is the format the caller will parse the archive as. With
    ``"xlsx"`` the workbook caps apply as well. The caller knows the
    format from the converter it chose, which a crafted archive cannot
    change, while part names inside the archive are the attacker's choice.
    """
    try:
        with src.open_binary() as fh, zipfile.ZipFile(fh) as z:
            infos = z.infolist()
            _check_archive_sizes(infos)
            if fmt == "xlsx":
                _check_workbook_parts(infos, _binary_parts(z, infos))
    except zipfile.BadZipFile:
        raise ArchiveRejected("not a valid OOXML (zip) archive") from None


def _check_archive_sizes(infos: list[zipfile.ZipInfo]) -> None:
    """The limits every OOXML archive meets: member count, total, ratio."""
    if len(infos) > MAX_MEMBERS:
        raise ArchiveRejected(
            f"archive has {len(infos)} members, more than the {MAX_MEMBERS} allowed"
        )
    total = 0
    for info in infos:
        total += info.file_size
        if total > MAX_TOTAL_UNCOMPRESSED:
            raise ArchiveRejected(
                f"total uncompressed size exceeds the "
                f"{MAX_TOTAL_UNCOMPRESSED}-byte limit"
            )
        if info.file_size > RATIO_CHECK_MIN_SIZE:
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > MAX_COMPRESSION_RATIO:
                raise ArchiveRejected(
                    f"member compression ratio {ratio:.0f}:1 exceeds the "
                    f"{MAX_COMPRESSION_RATIO}:1 limit"
                )


def _read_small(z: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> Any | None:
    """Parse a member of at most ``limit`` bytes, or None if it is unreadable."""
    try:
        with z.open(info) as f:
            data = f.read(limit + 1)
        if len(data) > limit:
            return None
        return fromstring(data)
    except (
        ParseError,
        OSError,
        zipfile.BadZipFile,
        ValueError,
        EOFError,
        RuntimeError,
        NotImplementedError,
        zlib.error,
    ):
        # A member Python's zipfile cannot inflate (a bad deflate stream,
        # an unsupported method, encryption) gives no exemption.
        return None


def _local(tag: Any) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _xml_targets(z: zipfile.ZipFile, infos: list[zipfile.ZipInfo]) -> set[str] | None:
    """Lowercased names of parts some relationship opens as anything but bytes.

    None when a relationship part is too large or unreadable, or all of
    them together pass the budget. The caller then exempts nothing.
    Targets are matched without case and also percent-decoded, so a
    spelling openpyxl might resolve differently only adds parts to the
    capped set.
    """
    targets: set[str] = set()
    budget = MAX_RELS_TOTAL
    for info in infos:
        if not _RELS_NAME_RE.search(info.filename):
            continue
        if info.file_size > MAX_RELS_PART or info.file_size > budget:
            return None
        budget -= info.file_size
        root = _read_small(z, info, MAX_RELS_PART)
        if root is None:
            return None
        # "xl/_rels/workbook.xml.rels" holds the relationships of
        # "xl/workbook.xml", so targets resolve against "xl".
        base = posixpath.dirname(posixpath.dirname(info.filename))
        for rel in root.iter():
            if _local(rel.tag) != "Relationship":
                continue
            if (rel.get("TargetMode") or "").lower() == "external":
                continue
            kind = (rel.get("Type") or "").rsplit("/", 1)[-1].lower()
            if kind in _BINARY_RELATIONSHIPS:
                continue
            target = rel.get("Target") or ""
            if target.startswith("/"):
                resolved = target.lstrip("/")
            else:
                resolved = posixpath.join(base, target)
            for name in (resolved, unquote(resolved)):
                targets.add(posixpath.normpath(name).lstrip("/").lower())
    return targets


def _binary_parts(z: zipfile.ZipFile, infos: list[zipfile.ZipInfo]) -> set[str]:
    """Names of members the workbook caps skip: images and other binaries.

    A member is skipped when ``[Content_Types].xml`` gives it, through an
    Override first and then the Default for its extension, an ``image/*``
    type or one of ``_BINARY_CONTENT_TYPES``, and no relationship opens
    it as XML. The second test keeps a sheet that is declared
    ``image/png`` but listed as a worksheet under the caps, since
    openpyxl follows the relationship, not the declared type. A member
    with an XML, unknown, or missing type stays capped, and the archive
    ceiling and ratio rule still cover every member.
    """
    content_types = next(
        (i for i in infos if i.filename == "[Content_Types].xml"), None
    )
    if content_types is None:
        return set()
    if content_types.file_size > MAX_CONTENT_TYPES_BYTES:
        raise ArchiveRejected(
            f"[Content_Types].xml inflates to {content_types.file_size} bytes, "
            f"more than the {MAX_CONTENT_TYPES_BYTES}-byte limit"
        )
    root = _read_small(z, content_types, MAX_CONTENT_TYPES_BYTES)
    if root is None:
        return set()
    defaults: dict[str, str] = {}
    overrides: dict[str, str] = {}
    for entry in root.iter():
        ctype = (entry.get("ContentType") or "").split(";")[0].strip().lower()
        if _local(entry.tag) == "Default":
            defaults[(entry.get("Extension") or "").lower()] = ctype
        elif _local(entry.tag) == "Override":
            part = (entry.get("PartName") or "").lstrip("/").lower()
            overrides[part] = ctype
    opened_as_xml = _xml_targets(z, infos)
    if opened_as_xml is None:
        return set()
    binary = set()
    for info in infos:
        name = info.filename.lower()
        if name in opened_as_xml:
            continue
        ctype = overrides.get(name)
        if ctype is None:
            ext = posixpath.splitext(name)[1].lstrip(".")
            ctype = defaults.get(ext, "") if ext else ""
        if ctype.startswith("image/") or ctype in _BINARY_CONTENT_TYPES:
            binary.add(info.filename)
    return binary


def _check_workbook_parts(infos: list[zipfile.ZipInfo], binary: set[str]) -> None:
    """Apply the workbook caps to every member except ``binary`` ones.

    openpyxl finds the workbook through ``[Content_Types].xml`` and the
    package relationships, and the sheets and shared strings through the
    workbook relationships. None of those lookups depend on a part's
    name or extension, so a sheet stored as ``xl/worksheets/sheet1.bin``
    or a workbook at ``xl/book.xml`` parses like any other. Every member
    counts unless ``_binary_parts`` showed it is an image or another
    binary openpyxl does not parse.
    """
    total = 0
    for info in infos:
        if info.filename in binary:
            continue
        if info.file_size > MAX_XLSX_XML_PART:
            raise ArchiveRejected(
                f"workbook XML part inflates to {info.file_size} bytes, more "
                f"than the {MAX_XLSX_XML_PART}-byte limit for spreadsheets"
            )
        total += info.file_size
        if total > MAX_XLSX_XML_TOTAL:
            raise ArchiveRejected(
                f"total workbook XML exceeds the {MAX_XLSX_XML_TOTAL}-byte "
                f"limit for spreadsheets"
            )
