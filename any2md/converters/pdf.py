"""PDF to Markdown converter (v1.0).

Phase 2: Docling primary backend with pymupdf4llm fallback. Backend
selection is automatic. If `docling` is importable we use it, otherwise
we fall back to pymupdf4llm. The `--high-fidelity` flag forces Docling
(enforced upstream in the CLI) but does not change the converter logic
beyond surfacing the requested backend in extracted_via.
"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from pathlib import Path
from typing import Any

import pymupdf
import pymupdf4llm

from any2md import _logging, pipeline
from any2md._docling import DoclingWarningCapture, has_docling, install_hint
from any2md._image_files import ImageWriter
from any2md._safe_open import SourceFile, as_source
from any2md.converters import add_warnings, is_quiet
from any2md.frontmatter import SourceMeta, compose
from any2md.heuristics import filter_organization
from any2md.pipeline import PipelineOptions
from any2md.utils import atomic_write_text, sanitize_filename


def _parse_pdf_authors(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts: list[str] = []
    for sep in (";", ",", "&", "/"):
        if sep in raw:
            parts = [p.strip() for p in raw.split(sep) if p.strip()]
            break
    return parts or [raw.strip()]


def _parse_pdf_date(raw: str | None) -> str | None:
    """Convert 'D:20250315120000Z' -> '2025-03-15'."""
    if not raw:
        return None
    s = raw.lstrip("D:").strip()
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return None


def _parse_pdf_metadata(doc: "pymupdf.Document") -> dict[str, object]:
    meta = doc.metadata or {}
    creator_raw = (meta.get("creator") or "").strip() or None
    org_result = filter_organization(creator_raw)
    return {
        "title_hint": (meta.get("title") or "").strip() or None,
        "authors": _parse_pdf_authors(meta.get("author")),
        "organization": org_result.organization,
        "produced_by": org_result.produced_by,
        "date": _parse_pdf_date(meta.get("creationDate")),
        "keywords": [
            k.strip() for k in (meta.get("keywords") or "").split(",") if k.strip()
        ],
    }


def _open_pdf(src: SourceFile, data: bytes | None = None) -> "pymupdf.Document":
    """Open the PDF from its path, or from the bytes of an opened source.

    pymupdf opens only a file name or bytes, not a file object. A
    descriptor-backed source is therefore read into memory once, and the
    caller passes those bytes here so the same buffer serves pymupdf and
    Docling.
    """
    if src.path is not None:
        return pymupdf.open(str(src.path))
    if data is None:
        data = src.read_bytes()
    return pymupdf.open(stream=data, filetype="pdf")


def pdf_looks_complex(pdf_path: Path | SourceFile) -> bool:
    """Cheap heuristic: is this PDF likely to produce artifacts on pymupdf4llm?

    Returns True when at least one signal suggests a complex layout that
    Docling would handle better:
      - Total pages > 5 AND
        (multi-column layout detected on any sampled page OR
         average chars-per-page < 200, which suggests a scanned PDF).

    Sampling: at most 5 pages, evenly distributed.
    """
    try:
        with _open_pdf(as_source(pdf_path)) as doc:
            return _doc_looks_complex(doc)
    except (OSError, ValueError, RuntimeError):
        return False


def _doc_looks_complex(doc: "pymupdf.Document") -> bool:
    """``pdf_looks_complex`` for a document the caller already opened."""
    try:
        page_count = len(doc)
        if page_count <= 5:
            return False

        # The early return above guarantees page_count > 5, so five
        # evenly spaced pages are always a strict subset of the doc.
        sample_idxs = [int(i * page_count / 5) for i in range(5)]

        total_chars = 0
        multi_column_seen = False
        for idx in sample_idxs:
            page = doc[idx]
            text = page.get_text("text") or ""
            total_chars += len(text)
            # Multi-column heuristic: collect block x-positions. If there
            # are clusters around two distinct x ranges with > 100 px
            # separation, flag.
            blocks = page.get_text("blocks") or []
            xs = sorted({round(b[0], 0) for b in blocks if len(b) >= 4})
            if len(xs) >= 4:
                # Check if there's a gap > page_width * 0.2 between
                # consecutive x-starts.
                pw = page.rect.width or 612
                for a, b in zip(xs, xs[1:]):
                    if b - a > pw * 0.2:
                        multi_column_seen = True
                        break

        avg_chars = total_chars / max(len(sample_idxs), 1)
        scanned_signal = avg_chars < 200
        return multi_column_seen or scanned_signal
    except (OSError, ValueError, RuntimeError):
        return False


def _load_pdf_models(converter: Any) -> None:
    """Load the PDF pipeline's models now, outside any warning capture.

    Docling loads them on the first convert otherwise. A converter
    without ``initialize_pipeline`` (an older Docling) loads them there.
    """
    initialize = getattr(converter, "initialize_pipeline", None)
    if initialize is None:
        return
    from docling.datamodel.base_models import InputFormat

    initialize(InputFormat.PDF)


def _extract_via_docling(
    pdf_path: Path | SourceFile,
    options: PipelineOptions,
    writer: ImageWriter | None = None,
    data: bytes | None = None,
    capture: DoclingWarningCapture | None = None,
) -> tuple[str, str]:
    """Returns (markdown, 'docling'). Raises on Docling errors.

    ``data`` is the file's bytes when the caller already read them, so
    a descriptor-backed source is not read a second time.

    With a ``writer`` (``--save-images``), picture images are staged as
    ``images/<pdf_stem>/imgN.png`` and linked from the body. The caller
    commits them with the final Markdown once it is written, or discards
    them if anything fails first.

    ``capture`` counts Python warnings from the conversion and export.
    The converter is built and its models loaded before it starts, so
    torch or transformers warnings from model loading never count.

    v1.1.0: uses the persistent ConverterCache rather than constructing
    a fresh DocumentConverter per call. On any convert exception the
    offending cache slot is evicted (guards against torch internal-
    state contamination from a malformed input).
    """
    from docling.datamodel.pipeline_options import PdfPipelineOptions

    from any2md._docling_cache import (
        evict_on_convert_failure,
        get_pdf_converter,
    )

    pipeline_opts = PdfPipelineOptions(
        do_ocr=options.ocr_figures,
        do_table_structure=True,
        generate_picture_images=options.save_images,
    )

    src = as_source(pdf_path)
    converter = get_pdf_converter(pipeline_opts)
    counted = capture if capture is not None else nullcontext()
    try:
        _load_pdf_models(converter)
        with counted:
            # Never a str: see SourceFile.docling_input.
            result = converter.convert(src.docling_input(data))
    except Exception:
        evict_on_convert_failure("pdf", pipeline_opts)
        raise

    # The same picture handling as DOCX, PPTX, and XLSX: a caption Docling
    # links to a picture becomes its figure line, and --save-images
    # writes images/<stem>/imgN.png and links it. A PDF has no alt text.
    from any2md.converters._office_pictures import (
        export_markdown,
        AltTexts,
        fill_pictures,
        prepare_pictures,
    )

    doc = result.document
    with capture if capture is not None else nullcontext():
        figures: dict[str, str] = {}
        if getattr(doc, "pictures", None):
            figures = prepare_pictures(doc, "pdf", AltTexts(), writer)
        md = fill_pictures(export_markdown(doc), figures)
    return md, "docling"


def _extract_via_pymupdf4llm(doc: "pymupdf.Document") -> tuple[str, str]:
    md = pymupdf4llm.to_markdown(
        doc,
        write_images=False,
        show_progress=False,
        force_text=True,
    )
    return md, "pymupdf4llm"


def convert_pdf(
    pdf_path: Path | SourceFile,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
    strip_links_flag: bool = False,
) -> bool:
    if options is None:
        options = PipelineOptions(strip_links=strip_links_flag)
    # A path, or a SourceFile the CLI already opened. Every read below
    # goes through ``src`` so a scanned file is never reopened by name.
    src = as_source(pdf_path)

    out_name = sanitize_filename(src.name)
    out_path = output_dir / out_name
    if out_path.exists() and not force:
        print(f"  SKIP (exists): {_logging.safe_oneline(out_name)}")
        return True

    # Images the Docling lane staged. They are published only after the
    # Markdown is written, with that Markdown, so a failed write keeps the
    # old images its old Markdown links and a link a pipeline stage drops
    # publishes nothing. Anything that fails first discards them.
    writer: ImageWriter | None = None
    try:
        # Backend override (PipelineOptions.backend). When set, honor the
        # caller's choice instead of the auto-select. ``mammoth`` is
        # invalid for PDFs, so fail the file with a clear error.
        if options.backend == "mammoth":
            _logging.fail(
                f"{src.name} -- backend 'mammoth' is not "
                f"valid for PDF input (mammoth processes DOCX only)."
            )
            return False

        if options.backend == "pymupdf4llm":
            use_docling = False
        elif options.backend == "docling":
            # Same install-required behavior as --high-fidelity. If
            # Docling isn't importable, fall through to the existing
            # auto-select path which will error via _extract_via_docling
            # below if Docling truly isn't usable. The CLI layer
            # pre-checks install for both --high-fidelity and
            # --backend docling, so this branch normally has Docling.
            use_docling = has_docling()
        else:
            use_docling = has_docling()

        # One parse per conversion: the complexity check, the metadata,
        # the pymupdf4llm body, and the fallback after a Docling failure
        # all share this Document. A path-backed source stays on disk.
        # Any other source is read once, and Docling gets the same bytes.
        data = None if src.path is not None else src.read_bytes()
        with _open_pdf(src, data) as doc:
            if not use_docling and options.backend is None and _doc_looks_complex(doc):
                install_hint()

            # Always extract metadata via PyMuPDF, independent of which
            # backend produces the markdown body.
            page_count = len(doc)
            props = _parse_pdf_metadata(doc)

            # Python warnings from a Docling run that returned. A run that
            # raised falls back to pymupdf4llm, and its warnings go with it.
            py_warnings: list[str] = []
            if use_docling:
                if options.save_images:
                    writer = ImageWriter(output_dir, src.name, overwrite=force)
                try:
                    cap = DoclingWarningCapture()
                    md_text, extracted_via = _extract_via_docling(
                        src, options, writer, data=data, capture=cap
                    )
                    py_warnings = cap.messages
                    lane = "structured"
                except Exception as e:  # noqa: BLE001 -- fall back rather than fail
                    # pymupdf4llm links no images.
                    if writer is not None:
                        writer.discard()
                        writer = None
                    _logging.warn(
                        f"Docling extraction failed for {src.name}: {e}; "
                        f"falling back to pymupdf4llm."
                    )
                    md_text, extracted_via = _extract_via_pymupdf4llm(doc)
                    lane = "text"
            else:
                md_text, extracted_via = _extract_via_pymupdf4llm(doc)
                lane = "text"
        # A closed pymupdf Document still references the bytes it was
        # opened from. Drop both so they can be freed before the text
        # pipeline runs.
        del data, doc

        md_text, warnings = pipeline.run(md_text, lane, options)
        warnings = py_warnings + warnings
        add_warnings(warnings)

        meta = SourceMeta(
            title_hint=props["title_hint"],
            authors=props["authors"],
            organization=props["organization"],
            date=(props["date"] or date.fromtimestamp(src.mtime()).isoformat()),
            keywords=props["keywords"],
            pages=page_count,
            word_count=None,
            source_file=src.name,
            source_url=None,
            doc_type="pdf",
            extracted_via=extracted_via,
            lane=lane,
            produced_by=props["produced_by"],
        )
        full = compose(md_text, meta, options, overrides=options.frontmatter_overrides)

        output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out_path, full)
        if writer is not None:
            writer.commit(full)
        suffix = f", {len(warnings)} warning(s)" if warnings else ""
        if not is_quiet():
            print(
                f"  OK: {_logging.safe_oneline(out_name)} "
                f"({page_count} pages, via {extracted_via}{suffix})"
            )
        return True

    except (OSError, ValueError, RuntimeError) as e:
        _logging.fail(f"{src.name} -- {e}")
        return False
    finally:
        # A no-op after commit. Otherwise it drops what failed to publish.
        if writer is not None:
            writer.discard()
