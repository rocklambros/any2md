"""DOCX to Markdown converter (v1.0).

Phase 2: Docling primary backend with mammoth+markdownify fallback.
Backend selection is automatic — if `docling` is importable we use it;
otherwise we fall back to mammoth+markdownify. Core property metadata
is always read directly from the DOCX zip independent of which backend
produces the markdown body.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from pathlib import Path

import mammoth
import markdownify

from any2md import pipeline
from any2md._docling import has_docling
from any2md.converters import add_warnings, is_quiet
from any2md.frontmatter import SourceMeta, compose
from any2md.heuristics import filter_organization
from any2md.pipeline import PipelineOptions
from any2md.utils import sanitize_filename

_NS_CORE = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dcterms": "http://purl.org/dc/terms/",
}
_NS_APP = {
    "ext": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
}


def _read_docx_metadata(docx_path: Path) -> dict[str, object]:
    out: dict[str, object] = {
        "title_hint": None,
        "authors": [],
        "organization": None,
        "produced_by": None,
        "date": None,
        "keywords": [],
    }
    try:
        with zipfile.ZipFile(docx_path) as z:
            try:
                with z.open("docProps/core.xml") as f:
                    root = ET.parse(f).getroot()
                title = root.findtext("dc:title", namespaces=_NS_CORE)
                if title:
                    out["title_hint"] = title.strip()
                creator = root.findtext("dc:creator", namespaces=_NS_CORE)
                if creator:
                    out["authors"] = [creator.strip()]
                kw = root.findtext("cp:keywords", namespaces=_NS_CORE) or ""
                out["keywords"] = [k.strip() for k in kw.split(",") if k.strip()]
                modified = root.findtext("dcterms:modified", namespaces=_NS_CORE)
                if modified:
                    out["date"] = modified[:10]
            except KeyError:
                pass
            try:
                with z.open("docProps/app.xml") as f:
                    root = ET.parse(f).getroot()
                company = root.findtext("ext:Company", namespaces=_NS_APP)
                application = root.findtext("ext:Application", namespaces=_NS_APP)
                # v1.0.2: Company takes priority for `organization` (real
                # legal entity); Application is software → goes to
                # `produced_by` via filter_organization. When Company is
                # absent we route Application through filter_organization
                # for both fields so a real-org Application name still
                # populates `organization`.
                if company and company.strip():
                    out["organization"] = company.strip()
                    if application and application.strip():
                        app_result = filter_organization(application.strip())
                        out["produced_by"] = app_result.produced_by
                elif application and application.strip():
                    app_result = filter_organization(application.strip())
                    out["organization"] = app_result.organization
                    out["produced_by"] = app_result.produced_by
            except KeyError:
                pass
    except (zipfile.BadZipFile, ET.ParseError):
        pass
    return out


def _extract_via_docling(docx_path: Path) -> tuple[str, str]:
    """Returns (markdown, 'docling'). Raises on Docling errors."""
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    result = converter.convert(str(docx_path))
    return result.document.export_to_markdown(), "docling"


def _extract_via_mammoth(docx_path: Path, options: PipelineOptions) -> tuple[str, str]:
    with open(docx_path, "rb") as f:
        html_result = mammoth.convert_to_html(f)
    md = markdownify.markdownify(
        html_result.value,
        heading_style="ATX",
        strip=["img"] if not options.save_images else [],
        bullets="-",
    )
    return md, "mammoth+markdownify"


def convert_docx(
    docx_path: Path,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
    strip_links_flag: bool = False,
) -> bool:
    if options is None:
        options = PipelineOptions(strip_links=strip_links_flag)

    out_name = sanitize_filename(docx_path.name)
    out_path = output_dir / out_name
    if out_path.exists() and not force:
        print(f"  SKIP (exists): {out_name}")
        return True

    try:
        # Backend override (PipelineOptions.backend). When set, honor the
        # caller's choice instead of the auto-select. ``pymupdf4llm`` is
        # invalid for DOCX — fail the file with a clear error.
        if options.backend == "pymupdf4llm":
            print(
                f"  FAIL: {docx_path.name} -- backend 'pymupdf4llm' is not "
                f"valid for DOCX input (pymupdf4llm processes PDF only).",
                file=sys.stderr,
            )
            return False

        if options.backend == "mammoth":
            md_text, extracted_via = _extract_via_mammoth(docx_path, options)
            lane = "text"
        elif options.backend == "docling":
            md_text, extracted_via = _extract_via_docling(docx_path)
            lane = "structured"
        elif has_docling():
            try:
                md_text, extracted_via = _extract_via_docling(docx_path)
                lane = "structured"
            except Exception as e:  # noqa: BLE001 — fall back rather than fail
                print(
                    f"  WARN: Docling extraction failed for {docx_path.name}: {e}; "
                    f"falling back to mammoth.",
                    file=sys.stderr,
                )
                md_text, extracted_via = _extract_via_mammoth(docx_path, options)
                lane = "text"
        else:
            md_text, extracted_via = _extract_via_mammoth(docx_path, options)
            lane = "text"

        md_text, warnings = pipeline.run(md_text, lane, options)
        add_warnings(warnings)

        props = _read_docx_metadata(docx_path)
        meta = SourceMeta(
            title_hint=props["title_hint"],
            authors=props["authors"],
            organization=props["organization"],
            date=(
                props["date"]
                or date.fromtimestamp(docx_path.stat().st_mtime).isoformat()
            ),
            keywords=props["keywords"],
            pages=None,
            word_count=len(md_text.split()),
            source_file=docx_path.name,
            source_url=None,
            doc_type="docx",
            extracted_via=extracted_via,
            lane=lane,
            produced_by=props["produced_by"],
        )
        full = compose(md_text, meta, options, overrides=options.frontmatter_overrides)

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(full, encoding="utf-8", newline="\n")
        wc = meta.word_count or 0
        suffix = f", {len(warnings)} warning(s)" if warnings else ""
        if not is_quiet():
            print(f"  OK: {out_name} ({wc} words, via {extracted_via}{suffix})")
        return True

    except (OSError, ValueError) as e:
        print(f"  FAIL: {docx_path.name} -- {e}", file=sys.stderr)
        return False
