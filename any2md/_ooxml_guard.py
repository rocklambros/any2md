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

import zipfile

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
    except zipfile.BadZipFile:
        raise ArchiveRejected("not a valid OOXML (zip) archive") from None

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

    if fmt == "xlsx":
        _check_workbook_parts(infos)


def _check_workbook_parts(infos: list[zipfile.ZipInfo]) -> None:
    """Apply the workbook caps to every member of the archive.

    openpyxl finds the workbook through ``[Content_Types].xml`` and the
    package relationships, and the sheets and shared strings through the
    workbook relationships. None of those lookups depend on a part's
    name or extension, so a sheet stored as ``xl/worksheets/sheet1.bin``
    or a workbook at ``xl/book.xml`` parses like any other. A filter on
    names would let such parts past, so every member counts. Embedded
    images count too, which costs an honest workbook with hundreds of
    MiB of pictures its conversion. That trade keeps the check free of
    any parsing of attacker-controlled XML.
    """
    total = 0
    for info in infos:
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
