"""Tests for the optional-part handling in _read_docx_metadata."""

from __future__ import annotations

import zipfile

from any2md.converters.docx import _read_docx_metadata

_DEFAULTS = {
    "title_hint": None,
    "authors": [],
    "organization": None,
    "produced_by": None,
    "date": None,
    "keywords": [],
}

_CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties
    xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
    xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:title>Only Core</dc:title>
</cp:coreProperties>
"""


def _write_docx(path, parts: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
        for name, body in parts.items():
            z.writestr(name, body)


def test_missing_docprops_parts_yield_defaults(tmp_path):
    docx = tmp_path / "bare.docx"
    _write_docx(docx, {})
    assert _read_docx_metadata(docx) == _DEFAULTS


def test_core_without_app_reads_core_only(tmp_path):
    docx = tmp_path / "core_only.docx"
    _write_docx(docx, {"docProps/core.xml": _CORE})
    meta = _read_docx_metadata(docx)
    assert meta["title_hint"] == "Only Core"
    assert meta["organization"] is None
    assert meta["produced_by"] is None


def test_malformed_core_xml_yields_defaults(tmp_path):
    docx = tmp_path / "broken_core.docx"
    _write_docx(docx, {"docProps/core.xml": "<cp:coreProperties"})
    assert _read_docx_metadata(docx) == _DEFAULTS
