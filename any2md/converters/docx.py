"""DOCX to Markdown converter (v1.0).

Phase 2: Docling primary backend with mammoth+markdownify fallback.
Backend selection is automatic — if `docling` is importable we use it;
otherwise we fall back to mammoth+markdownify. Core property metadata
is always read directly from the DOCX zip independent of which backend
produces the markdown body.
"""

from __future__ import annotations

import logging
import sys
import zipfile

from defusedxml.ElementTree import ParseError as _XmlParseError
from defusedxml.ElementTree import parse as _xml_parse
from datetime import date
from pathlib import Path

import mammoth
import markdownify

from any2md import _logging, pipeline
from any2md._docling import has_docling
from any2md._logging import _sanitize_log_text  # noqa: F401  # re-export shim for v1.1.x; remove in v1.2
from any2md.converters import add_warnings, is_quiet
from any2md.frontmatter import SourceMeta, compose
from any2md.heuristics import filter_organization
from any2md.pipeline import PipelineOptions
from any2md.utils import atomic_write_text, sanitize_filename


_DOCLING_MSWORD_LOGGER = "docling.backend.msword_backend"

_MAX_DOCX_METADATA_SIZE = 1 * 1024 * 1024  # 1 MB; core.xml/app.xml are typically <10 KB


def _safe_zip_open(
    z: zipfile.ZipFile, name: str, max_size: int = _MAX_DOCX_METADATA_SIZE
):
    """Open a fixed-name DOCX member after a declared-size sanity check.

    Defends against zip-bomb amplification: a malicious DOCX can declare
    an uncompressed_size of 10 GB for ``core.xml`` and bomb the XML
    parser. Raises ``ValueError`` (caught by ``convert_docx``'s existing
    handler -> file fails cleanly).
    """
    info = z.getinfo(name)
    if info.file_size > max_size:
        raise ValueError(
            f"{name} declared size {info.file_size} exceeds {max_size}-byte limit"
        )
    return z.open(name)


class _DoclingMswordWarningCapture:
    """Buffer WARNING+ records from Docling's DOCX backend logger.

    Used as a context manager around a Docling DOCX conversion to detect
    upstream's silent list-item-drop guard (msword_backend.py:1377/1675).
    Any captured records signal that Docling's Markdown output is
    incomplete; ``convert_docx`` consults this to decide whether to
    auto-retry with the mammoth lane.
    """

    def __init__(self) -> None:
        self._records: list[logging.LogRecord] = []
        self._handler: logging.Handler | None = None

    def __enter__(self) -> _DoclingMswordWarningCapture:
        records = self._records

        class _BufferHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _BufferHandler(level=logging.WARNING)
        logging.getLogger(_DOCLING_MSWORD_LOGGER).addHandler(handler)
        self._handler = handler
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._handler is not None:
            logging.getLogger(_DOCLING_MSWORD_LOGGER).removeHandler(self._handler)
            self._handler = None

    @property
    def messages(self) -> list[str]:
        return [r.getMessage() for r in self._records]


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
                with _safe_zip_open(z, "docProps/core.xml") as f:
                    root = _xml_parse(f).getroot()
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
                with _safe_zip_open(z, "docProps/app.xml") as f:
                    root = _xml_parse(f).getroot()
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
    except (zipfile.BadZipFile, _XmlParseError):
        pass
    return out


def _extract_via_docling(docx_path: Path) -> tuple[str, str, list[str]]:
    """Returns (markdown, 'docling', captured_warnings).

    ``captured_warnings`` is the list of WARNING+ messages emitted by
    Docling's ``msword_backend`` logger during the conversion. It is
    empty for clean runs. Raises on Docling errors.

    v1.1.0: uses the persistent ConverterCache rather than constructing
    a fresh DocumentConverter per call. On any convert exception the
    offending cache slot is evicted (guards against torch internal-
    state contamination from a malformed input).
    """
    from any2md._docling_cache import (
        evict_on_convert_failure,
        get_docx_converter,
    )

    converter = get_docx_converter()
    with _DoclingMswordWarningCapture() as cap:
        try:
            result = converter.convert(str(docx_path))
        except Exception:
            evict_on_convert_failure("docx", None)
            raise
    return result.document.export_to_markdown(), "docling", list(cap.messages)


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

        docling_warnings: list[str] = []
        if options.backend == "mammoth":
            md_text, extracted_via = _extract_via_mammoth(docx_path, options)
            lane = "text"
        elif options.backend == "docling":
            md_text, extracted_via, docling_warnings = _extract_via_docling(docx_path)
            lane = "structured"
        elif has_docling():
            try:
                md_text, extracted_via, docling_warnings = _extract_via_docling(
                    docx_path
                )
                lane = "structured"
            except Exception as e:  # noqa: BLE001 — fall back rather than fail
                print(
                    f"  WARN: Docling extraction failed for {docx_path.name}: {e}; "
                    f"falling back to mammoth.",
                    file=sys.stderr,
                )
                md_text, extracted_via = _extract_via_mammoth(docx_path, options)
                lane = "text"
                docling_warnings = []
        else:
            md_text, extracted_via = _extract_via_mammoth(docx_path, options)
            lane = "text"

        # v1.0.5: Docling's DOCX backend silently drops list items in a
        # known malformed-input path. When any msword_backend warning
        # fires, swap the Docling output for the mammoth lane (different
        # parser, generally more permissive). Captured warnings are
        # forwarded into the run-level warning bucket so --strict still
        # fails on them.
        if (
            docling_warnings
            and options.docx_fallback_on_warn
            and extracted_via == "docling"
        ):
            print(
                f"  FALLBACK: {docx_path.name} -- Docling emitted "
                f"{len(docling_warnings)} msword_backend warning(s); "
                f"re-running via mammoth (content may have been dropped "
                f"by Docling).",
                file=sys.stderr,
            )
            md_text, _ = _extract_via_mammoth(docx_path, options)
            extracted_via = "docling→mammoth (warning fallback)"
            lane = "text"
            add_warnings(
                [
                    f"docling.msword_backend: {_sanitize_log_text(m)}"
                    for m in docling_warnings
                ]
            )

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
        atomic_write_text(out_path, full)
        wc = meta.word_count or 0
        suffix = f", {len(warnings)} warning(s)" if warnings else ""
        if not is_quiet():
            print(f"  OK: {out_name} ({wc} words, via {extracted_via}{suffix})")
        return True

    except (OSError, ValueError) as e:
        _logging.fail(f"{docx_path.name} -- {e}")
        return False
