"""PowerPoint (.pptx) and Excel (.xlsx) to Markdown through Docling.

Docling is the only backend for both formats. Its MS PowerPoint and
MS Excel backends parse the OOXML package directly and load no ML
models. Without Docling installed the file fails with an install hint
and the batch moves on.

Output shape: one H1 for the deck or workbook, then one H2 section per
slide or sheet, with each section's own headings nested below it.
Docling writes each slide title as an H1. The converter moves it down
to H2 so every slide sits at one level, and S4 then enforces the
single H1. A slide without a title placeholder gets "Slide N". A sheet
has no title in Docling's Markdown, so its name becomes the heading.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

from any2md import _logging, pipeline
from any2md._docling import INSTALL_CMD, has_docling
from any2md._ooxml_guard import ArchiveRejected, check_ooxml_archive
from any2md._safe_open import SourceFile, as_source
from any2md.converters import add_warnings, is_quiet
from any2md.converters.docx import _read_docx_metadata
from any2md.frontmatter import SourceMeta, compose
from any2md.pipeline import PipelineOptions
from any2md.pipeline.structured import _render_heading, find_headings
from any2md.utils import atomic_write_text, sanitize_filename

OfficeFormat = Literal["pptx", "xlsx"]

# PowerPoint writes this title into docProps/core.xml when the author
# never set one. It names the application, not the document, so the
# file name is the better title.
_DEFAULT_TITLES = {"powerpoint presentation"}


def _one_line(text: str) -> str:
    """Collapse whitespace so a sheet or file name fits on a heading line."""
    return " ".join(text.split())


def _document_title(title_hint: str | None, source_name: str) -> str:
    """Pick the H1: the core-properties title, else the file stem."""
    if title_hint:
        hint = _one_line(title_hint)
        if hint and hint.casefold() not in _DEFAULT_TITLES:
            return hint
    stem = Path(source_name).stem.replace("_", " ")
    return _one_line(stem) or "Untitled"


def _label_value(label: Any) -> str:
    """Return a Docling label as its plain string value (``"sheet"``)."""
    return str(getattr(label, "value", label))


def _page_sections(doc: Any, fmt: OfficeFormat) -> list[tuple[str | None, str]] | None:
    """Split a converted deck or workbook into (heading, markdown) per page.

    Docling gives each slide and each sheet its own page. Returns None
    when the split cannot be trusted, and the caller then renders the
    whole document in one piece. Page-filtered export leaves out any
    item without page provenance, so one such item is enough to fall
    back: a missing heading costs less than missing content.
    """
    pages = sorted(getattr(doc, "pages", None) or {})
    if not pages:
        return None
    page_set = set(pages)
    for item, _level in doc.iterate_items():
        prov = getattr(item, "prov", None)
        if not prov or prov[0].page_no not in page_set:
            return None

    if fmt == "xlsx":
        # The Excel backend adds one sheet group and one page together,
        # in workbook order, so the two lists pair up by position.
        names = [
            g.name
            for g in getattr(doc, "groups", [])
            if _label_value(g.label) == "sheet"
        ]
        if len(names) != len(pages):
            return None

    sections: list[tuple[str | None, str]] = []
    for i, page_no in enumerate(pages):
        try:
            md = doc.export_to_markdown(page_no=page_no)
        except TypeError:
            # docling-core releases without page filtering.
            return None
        md = md.strip()
        if fmt == "xlsx":
            heading = _one_line(names[i]) or f"Sheet {i + 1}"
        else:
            # A slide with a title placeholder already opens with it.
            found = find_headings(md.split("\n"))
            opens_with_title = bool(found) and found[0][0] == 0
            heading = None if opens_with_title else f"Slide {page_no}"
        sections.append((heading, md))
    return sections


def _demote_headings(md: str, by: int) -> str:
    """Move every heading in ``md`` down ``by`` levels, capped at H6.

    Uses S4's own heading scan, so lines inside code fences, raw HTML,
    and block quotes stay as they are.
    """
    lines = md.split("\n")
    for heading in reversed(find_headings(lines)):
        first, last, level = heading
        lines[first : last + 1] = [_render_heading(lines, heading, min(level + by, 6))]
    return "\n".join(lines)


def _render_markdown(doc: Any, fmt: OfficeFormat, title: str) -> str:
    parts = [f"# {title}"]
    sections = _page_sections(doc, fmt)
    if sections is None:
        parts.append(doc.export_to_markdown())
    else:
        for heading, md in sections:
            # Blank slides and empty or hidden sheets add nothing to read.
            if not md:
                continue
            if heading is None:
                # The slide title becomes the H2 section heading.
                parts.append(_demote_headings(md, 1))
            else:
                parts.append(f"## {heading}")
                parts.append(_demote_headings(md, 2))
    return "\n\n".join(parts) + "\n"


def _convert_via_docling(src: SourceFile, fmt: OfficeFormat) -> Any:
    """Return the DoclingDocument for ``src``. Raises on Docling errors."""
    from any2md._docling_cache import evict_on_convert_failure, get_office_converter

    converter = get_office_converter(fmt)
    try:
        # Never a str: see SourceFile.docling_input.
        return converter.convert(src.docling_input()).document
    except Exception:
        evict_on_convert_failure(fmt, None)
        raise


def convert_office(
    source: Path | SourceFile,
    output_dir: Path,
    fmt: OfficeFormat,
    options: PipelineOptions | None = None,
    force: bool = False,
) -> bool:
    """Convert one .pptx or .xlsx file. Returns False when the file fails."""
    if options is None:
        options = PipelineOptions()
    # A path, or a SourceFile the CLI already opened. Every read below
    # goes through ``src`` so a scanned file is never reopened by name.
    src = as_source(source)
    label = fmt.upper()

    out_name = sanitize_filename(src.name)
    out_path = output_dir / out_name
    if out_path.exists() and not force:
        print(f"  SKIP (exists): {_logging.safe_oneline(out_name)}")
        return True

    if options.backend in ("pymupdf4llm", "mammoth"):
        _logging.fail(
            f"{src.name} -- backend '{options.backend}' is not valid for "
            f"{label} input ({label} converts through Docling only)."
        )
        return False
    if not has_docling():
        _logging.fail(
            f"{src.name} -- {label} input needs Docling, which is not "
            f"installed. Install it with: {INSTALL_CMD}"
        )
        return False

    try:
        # Before Docling or the docProps reader inflate anything.
        check_ooxml_archive(src)
    except ArchiveRejected as e:
        _logging.fail(f"{src.name} -- {e}")
        return False

    try:
        props = _read_docx_metadata(src)
        title = _document_title(props["title_hint"], src.name)
        doc = _convert_via_docling(src, fmt)
        md_text = _render_markdown(doc, fmt, title)
    except Exception as e:  # noqa: BLE001 -- untrusted input, fail this file only
        # Docling and its parsers raise many exception types on a corrupt
        # or hostile package. Any of them must end this file, not the batch.
        _logging.fail(f"{src.name} -- Docling could not convert this {label} file: {e}")
        return False

    try:
        md_text, warnings = pipeline.run(md_text, "structured", options)
        add_warnings(warnings)

        meta = SourceMeta(
            title_hint=props["title_hint"],
            authors=props["authors"],
            organization=props["organization"],
            date=(props["date"] or date.fromtimestamp(src.mtime()).isoformat()),
            keywords=props["keywords"],
            pages=None,
            word_count=len(md_text.split()),
            source_file=src.name,
            source_url=None,
            doc_type=fmt,
            extracted_via="docling",
            lane="structured",
            produced_by=props["produced_by"],
        )
        full = compose(md_text, meta, options, overrides=options.frontmatter_overrides)

        output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out_path, full)
    except (OSError, ValueError) as e:
        _logging.fail(f"{src.name} -- {e}")
        return False

    if not is_quiet():
        wc = meta.word_count or 0
        suffix = f", {len(warnings)} warning(s)" if warnings else ""
        print(
            f"  OK: {_logging.safe_oneline(out_name)} ({wc} words, via docling{suffix})"
        )
    return True


def convert_pptx(
    pptx_path: Path | SourceFile,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
) -> bool:
    return convert_office(pptx_path, output_dir, "pptx", options=options, force=force)


def convert_xlsx(
    xlsx_path: Path | SourceFile,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
) -> bool:
    return convert_office(xlsx_path, output_dir, "xlsx", options=options, force=force)
