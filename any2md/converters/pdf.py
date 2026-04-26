"""PDF to Markdown converter (v1.0).

Phase 2: Docling primary backend with pymupdf4llm fallback. Backend
selection is automatic — if `docling` is importable we use it; otherwise
we fall back to pymupdf4llm. The `--high-fidelity` flag forces Docling
(enforced upstream in the CLI) but does not change the converter logic
beyond surfacing the requested backend in extracted_via.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pymupdf
import pymupdf4llm

from any2md import pipeline
from any2md._docling import has_docling, install_hint
from any2md.converters import add_warnings, is_quiet
from any2md.frontmatter import SourceMeta, compose
from any2md.pipeline import PipelineOptions
from any2md.utils import sanitize_filename


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
    return {
        "title_hint": (meta.get("title") or "").strip() or None,
        "authors": _parse_pdf_authors(meta.get("author")),
        "organization": (meta.get("creator") or "").strip() or None,
        "date": _parse_pdf_date(meta.get("creationDate")),
        "keywords": [
            k.strip() for k in (meta.get("keywords") or "").split(",") if k.strip()
        ],
    }


def pdf_looks_complex(pdf_path: Path) -> bool:
    """Cheap heuristic: is this PDF likely to produce artifacts on pymupdf4llm?

    Returns True when at least one signal suggests a complex layout that
    Docling would handle better:
      - Total pages > 5 AND
        (multi-column layout detected on any sampled page OR
         average chars-per-page < 200 — suggests scanned PDF).

    Sampling: at most 5 pages, evenly distributed.
    """
    try:
        with pymupdf.open(str(pdf_path)) as doc:
            page_count = len(doc)
            if page_count <= 5:
                return False

            sample_idxs = (
                list(range(page_count))
                if page_count <= 5
                else [int(i * page_count / 5) for i in range(5)]
            )

            total_chars = 0
            multi_column_seen = False
            for idx in sample_idxs:
                page = doc[idx]
                text = page.get_text("text") or ""
                total_chars += len(text)
                # Multi-column heuristic: collect block x-positions; if there
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


def _extract_via_docling(
    pdf_path: Path, options: PipelineOptions, output_dir: Path
) -> tuple[str, str]:
    """Returns (markdown, 'docling'). Raises on Docling errors.

    When ``options.save_images`` is True, extracted picture images are
    written to ``<output_dir>/images/<pdf_stem>/imgN.png``.
    """
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pipeline_opts = PdfPipelineOptions(
        do_ocr=options.ocr_figures,
        do_table_structure=True,
        generate_picture_images=options.save_images,
    )

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts),
        }
    )
    result = converter.convert(str(pdf_path))

    if options.save_images:
        pictures = getattr(result.document, "pictures", None) or []
        if pictures:
            images_dir = output_dir / "images" / pdf_path.stem
            images_dir.mkdir(parents=True, exist_ok=True)
            for i, picture in enumerate(pictures):
                try:
                    pil_image = picture.get_image(result.document)
                    if pil_image is None:
                        continue
                    img_path = images_dir / f"img{i + 1}.png"
                    pil_image.save(str(img_path))
                except Exception as e:  # noqa: BLE001
                    print(
                        f"  WARN: failed to save image {i}: {e}",
                        file=sys.stderr,
                    )

    md = result.document.export_to_markdown()
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
    pdf_path: Path,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
    strip_links_flag: bool = False,
) -> bool:
    if options is None:
        options = PipelineOptions(strip_links=strip_links_flag)

    out_name = sanitize_filename(pdf_path.name)
    out_path = output_dir / out_name
    if out_path.exists() and not force:
        print(f"  SKIP (exists): {out_name}")
        return True

    try:
        # Backend override (PipelineOptions.backend). When set, honor the
        # caller's choice instead of the auto-select. ``mammoth`` is
        # invalid for PDFs — fail the file with a clear error.
        if options.backend == "mammoth":
            print(
                f"  FAIL: {pdf_path.name} -- backend 'mammoth' is not "
                f"valid for PDF input (mammoth processes DOCX only).",
                file=sys.stderr,
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

        if not use_docling and options.backend is None and pdf_looks_complex(pdf_path):
            install_hint()

        # Always extract metadata via PyMuPDF — independent of which
        # backend produces the markdown body.
        with pymupdf.open(str(pdf_path)) as doc:
            page_count = len(doc)
            props = _parse_pdf_metadata(doc)
            fallback_md = None
            if not use_docling:
                fallback_md, extracted_via = _extract_via_pymupdf4llm(doc)
                lane = "text"

        if use_docling:
            try:
                md_text, extracted_via = _extract_via_docling(
                    pdf_path, options, output_dir
                )
                lane = "structured"
            except Exception as e:  # noqa: BLE001 — fall back rather than fail
                print(
                    f"  WARN: Docling extraction failed for {pdf_path.name}: {e}; "
                    f"falling back to pymupdf4llm.",
                    file=sys.stderr,
                )
                with pymupdf.open(str(pdf_path)) as doc:
                    md_text, extracted_via = _extract_via_pymupdf4llm(doc)
                lane = "text"
        else:
            md_text = fallback_md

        md_text, warnings = pipeline.run(md_text, lane, options)
        add_warnings(warnings)

        meta = SourceMeta(
            title_hint=props["title_hint"],
            authors=props["authors"],
            organization=props["organization"],
            date=(
                props["date"]
                or date.fromtimestamp(pdf_path.stat().st_mtime).isoformat()
            ),
            keywords=props["keywords"],
            pages=page_count,
            word_count=None,
            source_file=pdf_path.name,
            source_url=None,
            doc_type="pdf",
            extracted_via=extracted_via,
            lane=lane,
        )
        full = compose(
            md_text, meta, options, overrides=options.frontmatter_overrides
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(full, encoding="utf-8", newline="\n")
        suffix = f", {len(warnings)} warning(s)" if warnings else ""
        if not is_quiet():
            print(
                f"  OK: {out_name} ({page_count} pages, via {extracted_via}{suffix})"
            )
        return True

    except (OSError, ValueError, RuntimeError) as e:
        print(f"  FAIL: {pdf_path.name} -- {e}", file=sys.stderr)
        return False
