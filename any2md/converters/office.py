"""PowerPoint (.pptx) and Excel (.xlsx) to Markdown through Docling.

Docling is the only backend for both formats. Its MS PowerPoint and
MS Excel backends parse the OOXML package directly and load no ML
models. Without Docling installed the file fails with an install hint
and the batch moves on.

Output shape: one H1 for the deck or workbook, then one H2 section per
slide or sheet, with each section's own headings nested below it.
The text of a slide's title placeholder becomes its H2, wherever the
placeholder sits on the slide. A slide without title text gets
"Slide N". A sheet has no title in Docling's Markdown, so its name
becomes the heading.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

from any2md import _logging, pipeline
from any2md._docling import (
    INSTALL_CMD,
    DoclingLogCapture,
    DoclingWarningCapture,
    has_docling,
)
from any2md._logging import _sanitize_log_text
from any2md._image_files import ImageWriter
from any2md._ooxml_guard import ArchiveRejected, check_ooxml_archive
from any2md._safe_open import SourceFile, as_source
from any2md.converters import add_warnings, is_quiet
from any2md.converters._office_pictures import (
    PICTURE_TOKEN,
    fill_pictures,
    prepare_pictures,
    read_alt_texts,
)
from any2md.converters.docx import _read_docx_metadata
from any2md.frontmatter import SourceMeta, compose
from any2md.pipeline import PipelineOptions
from any2md.pipeline.structured import _render_heading, find_headings
from any2md.utils import atomic_write_text, sanitize_filename

OfficeFormat = Literal["pptx", "xlsx"]

# Docling's backend logger for each format. A WARNING there means the
# backend skipped something (a chart it could not read, a malformed
# hyperlink, an image it could not decode), so it counts toward
# --strict like any other converter warning.
_BACKEND_LOGGERS = {
    "pptx": "docling.backend.mspowerpoint_backend",
    "xlsx": "docling.backend.msexcel_backend",
}

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


def _split_labels() -> tuple[set[Any], set[Any]]:
    """Split Docling's default export labels into (title, everything else).

    A lazy import, so this module loads without Docling installed.
    """
    from docling_core.types.doc.document import DEFAULT_EXPORT_LABELS

    title = {lab for lab in DEFAULT_EXPORT_LABELS if _label_value(lab) == "title"}
    return title, set(DEFAULT_EXPORT_LABELS) - title


def _slide_title(doc: Any, page_no: int, title_labels: set[Any]) -> str:
    """Return the text of the slide's title placeholder, or "" without one.

    Docling labels every paragraph of a title or centered-title
    placeholder TITLE, and places it where the shape sits on the slide,
    so a picture or text box above the title comes first. Exporting the
    TITLE items alone finds the title wherever it sits, keeps Docling's
    Markdown escaping, and joins a title of several paragraphs into one
    heading line.
    """
    md = doc.export_to_markdown(page_no=page_no, labels=title_labels)
    parts = (line.lstrip("#").strip() for line in md.splitlines())
    return _one_line(" ".join(p for p in parts if p))


def _page_sections(
    doc: Any, fmt: OfficeFormat, figures: dict[int, str]
) -> list[tuple[str, str, bool]] | None:
    """Split a converted deck or workbook into sections, one per page.

    Each section is (heading, markdown, keep when empty). A slide whose
    title placeholder holds text, and a slide or sheet with a picture,
    keep their section even when nothing in it survives the pipeline.

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

    title_labels, body_labels = _split_labels() if fmt == "pptx" else (set(), set())
    sections: list[tuple[str, str, bool]] = []
    for i, page_no in enumerate(pages):
        title = ""
        export: dict[str, Any] = {
            "page_no": page_no,
            "image_placeholder": PICTURE_TOKEN,
        }
        try:
            if fmt == "xlsx":
                heading = _one_line(names[i]) or f"Sheet {i + 1}"
            else:
                title = _slide_title(doc, page_no, title_labels)
                heading = title or f"Slide {page_no}"
                # The title is the section heading, so the body leaves it
                # out. Without title text the body keeps every label, so
                # a title item Docling could not give text loses nothing.
                if title:
                    export["labels"] = body_labels
            md = doc.export_to_markdown(**export)
        except TypeError:
            # docling-core releases without page filtering.
            return None
        has_picture = PICTURE_TOKEN in md
        md = fill_pictures(doc, md, figures, page_no=page_no).strip()
        sections.append((heading, md, bool(title) or has_picture))
    return sections


def _demote_headings(md: str, by: int) -> str:
    """Move every heading in ``md`` down ``by`` levels, capped at H6.

    Uses S4's own heading scan, so lines inside code fences, raw HTML,
    and block quotes stay as they are.
    """
    lines = md.split("\n")
    for heading in reversed(find_headings(md)):
        first, last, level = heading
        lines[first : last + 1] = [_render_heading(lines, heading, min(level + by, 6))]
    return "\n".join(lines)


def _render_markdown(
    doc: Any, fmt: OfficeFormat, title: str, figures: dict[int, str] | None = None
) -> str:
    """Render the deck or workbook. ``figures`` comes from ``prepare_pictures``."""
    figures = figures or {}
    parts = [f"# {title}"]
    sections = _page_sections(doc, fmt, figures)
    if sections is None:
        md = doc.export_to_markdown(image_placeholder=PICTURE_TOKEN)
        parts.append(fill_pictures(doc, md, figures))
    else:
        for heading, md, keep_empty in sections:
            # Blank slides and empty or hidden sheets add nothing to read.
            if not md and not keep_empty:
                continue
            parts.append(f"## {heading}")
            if md:
                parts.append(_demote_headings(md, 2))
    return "\n\n".join(parts) + "\n"


def _prepare_figures(
    doc: Any, src: SourceFile, fmt: OfficeFormat, writer: ImageWriter | None
) -> dict[int, str]:
    """Build each picture's Markdown, staging images under --save-images.

    Images go to ``<output>/images/<stem>/imgN.png``, the layout every
    converter uses, and the body links them by that relative path. The
    caller commits them once the Markdown is written.
    """
    if not getattr(doc, "pictures", None):
        return {}
    return prepare_pictures(doc, fmt, read_alt_texts(src, fmt), writer)


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

    # With --force, images are regenerated and stale ones removed, even
    # when the document has no pictures left. They are published only
    # after the Markdown is written, and dropped if anything fails first.
    writer = (
        ImageWriter(output_dir, src.stem, overwrite=force)
        if options.save_images
        else None
    )
    try:
        props = _read_docx_metadata(src)
        title = _document_title(props["title_hint"], src.name)
        # The outer capture on the whole "docling" tree gives every Docling
        # record a handler. Without one, Python prints an unhandled WARNING
        # through logging.lastResort, and a failed file would show Docling's
        # "Input document ... is not valid." above the FAIL line. Its records
        # are dropped: the FAIL line already carries Docling's error. Records
        # still propagate, so a caller's own logging setup sees them.
        # docling-core also raises Python warnings, during conversion and
        # during Markdown export, so both run inside the warning capture.
        with (
            DoclingLogCapture("docling"),
            DoclingLogCapture(_BACKEND_LOGGERS[fmt]) as cap,
            DoclingWarningCapture() as py_warnings,
        ):
            doc = _convert_via_docling(src, fmt)
            figures = _prepare_figures(doc, src, fmt, writer)
            md_text = _render_markdown(doc, fmt, title, figures)
    except Exception as e:  # noqa: BLE001 -- untrusted input, fail this file only
        # Docling and its parsers raise many exception types on a corrupt
        # or hostile package. Any of them must end this file, not the batch.
        if writer is not None:
            writer.discard()
        _logging.fail(f"{src.name} -- Docling could not convert this {label} file: {e}")
        return False

    try:
        md_text, warnings = pipeline.run(md_text, "structured", options)
        warnings = (
            [f"{r.name}: {_sanitize_log_text(r.getMessage())}" for r in cap.records]
            + py_warnings.messages
            + warnings
        )
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
        if writer is not None:
            writer.discard()
        _logging.fail(f"{src.name} -- {e}")
        return False
    if writer is not None:
        writer.commit()

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
