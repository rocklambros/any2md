"""Tests for the optional-part handling in _read_docx_metadata."""

from __future__ import annotations

import zipfile

import pytest

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


def test_pretty_printed_modified_date_is_stripped_before_slicing(tmp_path):
    """Indented dcterms:modified text must still yield YYYY-MM-DD."""
    core = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties
    xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
    xmlns:dcterms="http://purl.org/dc/terms/">
  <dcterms:modified>
        2025-03-01T10:00:00Z
  </dcterms:modified>
</cp:coreProperties>
"""
    docx = tmp_path / "pretty.docx"
    _write_docx(docx, {"docProps/core.xml": core})
    assert _read_docx_metadata(docx)["date"] == "2025-03-01"


def _core_with_modified(text: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties
    xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
    xmlns:dcterms="http://purl.org/dc/terms/">
  <dcterms:modified>{text}</dcterms:modified>
</cp:coreProperties>
"""


@pytest.mark.parametrize(
    "modified",
    [
        "٢٠٢٥-٠٣-٠١T00:00:00Z",
        "March 3, 2024 10:00",
        "20250301T100000Z",
        "2025-13-40T00:00:00Z",
    ],
)
def test_malformed_modified_date_yields_no_date(tmp_path, modified):
    """A date that is not an ASCII calendar YYYY-MM-DD is dropped (mtime fallback)."""
    docx = tmp_path / "bad_date.docx"
    _write_docx(docx, {"docProps/core.xml": _core_with_modified(modified)})
    assert _read_docx_metadata(docx)["date"] is None
