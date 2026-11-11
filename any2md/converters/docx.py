"""DOCX to Markdown converter (v1.0).

Phase 2: Docling primary backend with mammoth+markdownify fallback.
Backend selection is automatic — if `docling` is importable we use it;
otherwise we fall back to mammoth+markdownify. Core property metadata
is always read directly from the DOCX zip independent of which backend
produces the markdown body.
"""

from __future__ import annotations

import importlib.metadata
import re
import zipfile

from defusedxml.ElementTree import ParseError as _XmlParseError
from defusedxml.ElementTree import parse as _xml_parse
from datetime import date
from pathlib import Path

import mammoth
import markdownify

from any2md import _logging, pipeline
from any2md._docling import DoclingLogCapture, DoclingWarningCapture, has_docling
from any2md._ooxml_guard import check_ooxml_archive
from any2md._logging import _sanitize_log_text  # noqa: F401  # re-export shim for v1.1.x; remove in v1.2
from any2md._safe_open import SourceFile, as_source
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


class _DoclingMswordWarningCapture(DoclingLogCapture):
    """Buffer WARNING+ records from Docling's DOCX backend logger.

    Used as a context manager around a Docling DOCX conversion to detect
    upstream's silent list-item-drop guard (msword_backend.py:1377/1675).
    Any captured records signal that Docling's Markdown output is
    incomplete; ``convert_docx`` consults this to decide whether to
    auto-retry with the mammoth lane.
    """

    def __init__(self) -> None:
        super().__init__(_DOCLING_MSWORD_LOGGER)


_NS_CORE = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dcterms": "http://purl.org/dc/terms/",
}
_NS_APP = {
    "ext": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
}


def _read_docx_metadata(docx_path: Path | SourceFile) -> dict[str, object]:
    out: dict[str, object] = {
        "title_hint": None,
        "authors": [],
        "organization": None,
        "produced_by": None,
        "date": None,
        "keywords": [],
    }
    try:
        with as_source(docx_path).open_binary() as fh, zipfile.ZipFile(fh) as z:
            # Both docProps parts are optional in OOXML, so a missing part
            # leaves the defaults in place. Testing membership up front,
            # rather than catching KeyError, keeps a KeyError from any
            # other cause inside the parse visible.
            members = set(z.namelist())
            if "docProps/core.xml" in members:
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
            if "docProps/app.xml" in members:
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
    except (zipfile.BadZipFile, _XmlParseError):
        # Metadata is best effort. convert_docx reads it after the body
        # extracted cleanly, so a corrupt archive has already failed there.
        # What lands here in practice is malformed docProps XML in an
        # otherwise readable file, and bad metadata should not fail a
        # conversion whose body succeeded. The defaults stand in.
        pass
    return out


def _extract_via_docling(
    docx_path: Path | SourceFile,
) -> tuple[str, str, list[str]]:
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
            # Never a str: see SourceFile.docling_input.
            result = converter.convert(as_source(docx_path).docling_input())
        except Exception:
            evict_on_convert_failure("docx", None)
            raise
    return result.document.export_to_markdown(), "docling", list(cap.messages)


# mammoth 1.11.0 added ``external_file_access`` and turned it off by
# default (CVE-2025-11849). Earlier releases open a linked image's target
# with ``urlopen`` or ``open`` and accept no switch to stop it.
_MAMMOTH_SAFE_VERSION = (1, 11)


def _installed_mammoth_version() -> str:
    try:
        return importlib.metadata.version("mammoth")
    except importlib.metadata.PackageNotFoundError:
        return ""


def _mammoth_blocks_external_files() -> bool:
    match = re.match(r"(\d+)\.(\d+)", _installed_mammoth_version())
    if match is None:
        # Unknown version: assume the unsafe behavior.
        return False
    return (int(match.group(1)), int(match.group(2))) >= _MAMMOTH_SAFE_VERSION


# Emits an <img> with alt text and no src, so mammoth never calls
# ``image.open()``. markdownify strips the tag when images are not saved.
_skip_image_bytes = mammoth.images.img_element(lambda image: {})


def _mammoth_kwargs(save_images: bool) -> dict:
    if not _mammoth_blocks_external_files():
        # mammoth's image object does not say whether bytes come from the
        # DOCX zip or from a link, so on an unsafe release no image is read.
        return {"convert_image": _skip_image_bytes}
    kwargs: dict = {"external_file_access": False}
    if not save_images:
        # The image is stripped from the output anyway, so reading and
        # base64-encoding its bytes is wasted work.
        kwargs["convert_image"] = _skip_image_bytes
    return kwargs


def _extract_via_mammoth(
    docx_path: Path | SourceFile, options: PipelineOptions
) -> tuple[str, str]:
    with as_source(docx_path).open_binary() as f:
        html_result = mammoth.convert_to_html(f, **_mammoth_kwargs(options.save_images))
    md = markdownify.markdownify(
        html_result.value,
        heading_style="ATX",
        strip=["img"] if not options.save_images else [],
        bullets="-",
        # mammoth never emits <thead>; without inference markdownify 1.x
        # writes an empty header row and demotes the real header.
        table_infer_header=True,
    )
    return md, "mammoth+markdownify"


def convert_docx(
    docx_path: Path | SourceFile,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
    strip_links_flag: bool = False,
) -> bool:
    if options is None:
        options = PipelineOptions(strip_links=strip_links_flag)
    # A path, or a SourceFile the CLI already opened. Every read below
    # goes through ``src`` so a scanned file is never reopened by name.
    src = as_source(docx_path)

    out_name = sanitize_filename(src.name)
    out_path = output_dir / out_name
    if out_path.exists() and not force:
        print(f"  SKIP (exists): {_logging.safe_oneline(out_name)}")
        return True

    try:
        # Before mammoth, Docling, or the docProps reader inflate anything.
        # A rejection is a ValueError, reported below as a per-file FAIL.
        check_ooxml_archive(src)

        # Backend override (PipelineOptions.backend). When set, honor the
        # caller's choice instead of the auto-select. ``pymupdf4llm`` is
        # invalid for DOCX — fail the file with a clear error.
        if options.backend == "pymupdf4llm":
            _logging.fail(
                f"{src.name} -- backend 'pymupdf4llm' is not "
                f"valid for DOCX input (pymupdf4llm processes PDF only)."
            )
            return False

        docling_warnings: list[str] = []
        # Python warnings from a Docling run that returned. A run that
        # raised falls back to mammoth, and its warnings go with it.
        py_warnings: list[str] = []
        if options.backend == "mammoth":
            md_text, extracted_via = _extract_via_mammoth(src, options)
            lane = "text"
        elif options.backend == "docling":
            with DoclingWarningCapture() as cap:
                md_text, extracted_via, docling_warnings = _extract_via_docling(src)
            py_warnings = cap.messages
            lane = "structured"
        elif has_docling():
            try:
                with DoclingWarningCapture() as cap:
                    md_text, extracted_via, docling_warnings = _extract_via_docling(src)
                py_warnings = cap.messages
                lane = "structured"
            except Exception as e:  # noqa: BLE001 — fall back rather than fail
                _logging.warn(
                    f"Docling extraction failed for {src.name}: {e}; "
                    f"falling back to mammoth."
                )
                md_text, extracted_via = _extract_via_mammoth(src, options)
                lane = "text"
                docling_warnings = []
        else:
            md_text, extracted_via = _extract_via_mammoth(src, options)
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
            _logging.warn(
                f"{src.name} -- Docling emitted "
                f"{len(docling_warnings)} msword_backend warning(s); "
                f"re-running via mammoth (content may have been dropped "
                f"by Docling).",
                prefix="FALLBACK",
            )
            md_text, _ = _extract_via_mammoth(src, options)
            extracted_via = "docling→mammoth (warning fallback)"
            lane = "text"
            add_warnings(
                [
                    f"docling.msword_backend: {_sanitize_log_text(m)}"
                    for m in docling_warnings
                ]
            )

        md_text, warnings = pipeline.run(md_text, lane, options)
        warnings = py_warnings + warnings
        add_warnings(warnings)

        props = _read_docx_metadata(src)
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
            print(
                f"  OK: {_logging.safe_oneline(out_name)} "
                f"({wc} words, via {extracted_via}{suffix})"
            )
        return True

    except (OSError, ValueError) as e:
        _logging.fail(f"{src.name} -- {e}")
        return False
