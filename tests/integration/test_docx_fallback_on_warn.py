"""Integration tests for the Docling→mammoth auto-retry on msword warnings.

Docling's DOCX backend silently drops list items when their tracked
parent isn't a `ListGroup` (msword_backend.py:1377/1675). When that
warning fires we want any2md to auto-retry the file with mammoth, which
uses a different parsing path. These tests stub `_extract_via_docling`
so they don't depend on a real DOCX that reproduces the upstream bug.
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

import yaml

import any2md.converters.docx as docx_mod
from any2md.converters import collected_warnings, reset_warnings
from any2md.converters.docx import (
    _DoclingMswordWarningCapture,
    convert_docx,
)
from any2md.pipeline import PipelineOptions


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""

_CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/"
                   xmlns:dcterms="http://purl.org/dc/terms/">
  <dc:title>Listy Doc</dc:title>
  <dc:creator>Test Author</dc:creator>
  <dcterms:modified xsi:type="dcterms:W3CDTF" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">2026-04-26T00:00:00Z</dcterms:modified>
</cp:coreProperties>
"""

_APP = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
</Properties>
"""

# Minimal document with one heading, one paragraph, one (mammoth-parseable)
# bullet list — enough that mammoth produces a non-trivial Markdown body.
_DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Listy Doc</w:t></w:r></w:p>
    <w:p><w:r><w:t>Body before list.</w:t></w:r></w:p>
    <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Item one</w:t></w:r></w:p>
    <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Item two</w:t></w:r></w:p>
  </w:body>
</w:document>
"""


def _build_listy_docx(out_path: Path) -> None:
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("docProps/core.xml", _CORE)
        z.writestr("docProps/app.xml", _APP)
        z.writestr("word/document.xml", _DOCUMENT)


# ---------- _DoclingMswordWarningCapture (unit-ish behavior) -------------


def test_capture_collects_warning_records():
    cap = _DoclingMswordWarningCapture()
    log = logging.getLogger("docling.backend.msword_backend")
    with cap:
        log.warning("Parent element of the list item is not a ListGroup. Ignored.")
        log.info("not captured (below WARNING)")
    assert len(cap.messages) == 1
    assert "ListGroup" in cap.messages[0]


def test_capture_handler_detached_after_exit():
    cap = _DoclingMswordWarningCapture()
    log = logging.getLogger("docling.backend.msword_backend")
    before = list(log.handlers)
    with cap:
        pass
    assert log.handlers == before


def test_capture_records_from_child_loggers():
    """Child-logger records propagate up; capture must see them."""
    cap = _DoclingMswordWarningCapture()
    child = logging.getLogger("docling.backend.msword_backend.sub")
    with cap:
        child.warning("nested warning")
    assert any("nested warning" in m for m in cap.messages)


# ---------- convert_docx fallback behavior --------------------------------


def _stub_docling_with_warning(
    monkeypatch,
    message: str = "Parent element of the list item is not a ListGroup. The list item will be ignored.",
):
    """Make `_extract_via_docling` emit a docling msword warning and return stub MD."""
    log = logging.getLogger("docling.backend.msword_backend")

    def _fake(docx_path):
        # Use the real capture machinery: emit through the same logger
        # the capture is attached to.
        log.warning(message)
        return "# Docling output\n", "docling", [message]

    monkeypatch.setattr(docx_mod, "_extract_via_docling", _fake)


def test_fallback_fires_by_default(tmp_path, tmp_output_dir, monkeypatch, capsys):
    monkeypatch.setattr(docx_mod, "has_docling", lambda: True)

    def _fake(docx_path):
        return (
            "# Docling output\n",
            "docling",
            ["Parent element of the list item is not a ListGroup. Ignored."],
        )

    monkeypatch.setattr(docx_mod, "_extract_via_docling", _fake)

    docx = tmp_path / "listy.docx"
    _build_listy_docx(docx)

    reset_warnings()
    ok = convert_docx(docx, tmp_output_dir, options=PipelineOptions(), force=True)
    assert ok

    out = next(tmp_output_dir.glob("*.md")).read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    body = out[end + 5 :]

    # Frontmatter reflects the fallback explicitly.
    assert fm["extracted_via"] == "docling→mammoth (warning fallback)"
    # Mammoth output reached the body — Docling's "# Docling output" is gone.
    assert "Docling output" not in body
    assert "Listy Doc" in body or "Item" in body

    # Warning surfaced into collected_warnings so --strict catches it.
    warns = collected_warnings()
    assert any("ListGroup" in w for w in warns)

    # Stderr (or stdout via OK line suffix) carries a user-visible note.
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "fallback" in combined.lower() or "fell back" in combined.lower()


def test_fallback_disabled_keeps_docling(tmp_path, tmp_output_dir, monkeypatch):
    monkeypatch.setattr(docx_mod, "has_docling", lambda: True)

    def _fake(docx_path):
        return (
            "# Docling output\n",
            "docling",
            ["Parent element of the list item is not a ListGroup. Ignored."],
        )

    monkeypatch.setattr(docx_mod, "_extract_via_docling", _fake)

    docx = tmp_path / "listy.docx"
    _build_listy_docx(docx)

    reset_warnings()
    options = PipelineOptions(docx_fallback_on_warn=False)
    ok = convert_docx(docx, tmp_output_dir, options=options, force=True)
    assert ok

    out = next(tmp_output_dir.glob("*.md")).read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    body = out[end + 5 :]
    # Fallback disabled: Docling output retained, no fallback marker.
    assert fm["extracted_via"] == "docling"
    assert "Docling output" in body


def test_no_warnings_no_fallback(tmp_path, tmp_output_dir, monkeypatch):
    monkeypatch.setattr(docx_mod, "has_docling", lambda: True)

    def _fake(docx_path):
        return "# Clean Docling output\n", "docling", []

    monkeypatch.setattr(docx_mod, "_extract_via_docling", _fake)

    docx = tmp_path / "listy.docx"
    _build_listy_docx(docx)

    reset_warnings()
    ok = convert_docx(docx, tmp_output_dir, options=PipelineOptions(), force=True)
    assert ok

    out = next(tmp_output_dir.glob("*.md")).read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    body = out[end + 5 :]
    assert fm["extracted_via"] == "docling"
    assert "Clean Docling output" in body


def test_explicit_docling_backend_still_falls_back(
    tmp_path, tmp_output_dir, monkeypatch
):
    """User passed --backend docling but Docling emitted warnings: still retry.

    The fallback flag is independent of backend selection; explicit
    `--backend docling` doesn't pin the user to a lossy result.
    """
    monkeypatch.setattr(docx_mod, "has_docling", lambda: True)

    def _fake(docx_path):
        return (
            "# Docling output\n",
            "docling",
            ["Parent element of the list item is not a ListGroup. Ignored."],
        )

    monkeypatch.setattr(docx_mod, "_extract_via_docling", _fake)

    docx = tmp_path / "listy.docx"
    _build_listy_docx(docx)

    options = PipelineOptions(backend="docling")
    reset_warnings()
    ok = convert_docx(docx, tmp_output_dir, options=options, force=True)
    assert ok
    out = next(tmp_output_dir.glob("*.md")).read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    assert fm["extracted_via"] == "docling→mammoth (warning fallback)"
