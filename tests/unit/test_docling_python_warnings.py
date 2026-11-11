"""Python warnings raised inside a Docling DOCX or PDF conversion.

docling-core reports some document problems with ``warnings.warn``. The
converters record them, count them like Docling's logged warnings, and
keep the raw library text off stderr. These tests stub the Docling call
so they run without Docling installed.
"""

from __future__ import annotations

import warnings

import any2md.converters.docx as docx_mod
from any2md._docling import DoclingWarningCapture
import any2md.converters.pdf as pdf_mod
from any2md.converters import collected_warnings, reset_warnings
from any2md.pipeline import PipelineOptions

_BBOX = "Provenance bbox coordinate b on page 2 is outside page bounds: value=9"


_DOCLING_FILE = "/venv/lib/python3.12/site-packages/docling_core/types/doc/document.py"


def _docling_warning(args, kwargs):
    """Raise the bbox warning from a docling-core file, inside the capture
    the converter passed (positionally for DOCX, by name for PDF)."""
    capture = kwargs.get("capture") or next(
        a for a in args if isinstance(a, DoclingWarningCapture)
    )
    with capture:
        warnings.warn_explicit(
            _BBOX, UserWarning, _DOCLING_FILE, 333, module="docling_core.types"
        )


def _warn_then(result):
    def fake(*args, **kwargs):
        _docling_warning(args, kwargs)
        return result

    return fake


def test_docx_docling_warning_is_counted_not_printed(
    fixture_dir, tmp_output_dir, monkeypatch, capsys
):
    monkeypatch.setattr(docx_mod, "has_docling", lambda: True)
    monkeypatch.setattr(
        docx_mod,
        "_extract_via_docling",
        _warn_then(("# Title\n\nBody.\n", "docling", [])),
    )
    reset_warnings()

    assert docx_mod.convert_docx(
        fixture_dir / "table_heavy.docx", tmp_output_dir, force=True
    )

    got = collected_warnings()
    reset_warnings()
    assert f"UserWarning: {_BBOX}" in got
    captured = capsys.readouterr()
    assert "UserWarning" not in captured.err
    assert "outside page bounds" not in captured.err
    assert "1 warning(s)" in captured.out


def test_pdf_docling_warning_is_counted_not_printed(
    fixture_dir, tmp_output_dir, monkeypatch, capsys
):
    monkeypatch.setattr(pdf_mod, "has_docling", lambda: True)
    monkeypatch.setattr(
        pdf_mod, "_extract_via_docling", _warn_then(("# Title\n\nBody.\n", "docling"))
    )
    reset_warnings()

    assert pdf_mod.convert_pdf(
        fixture_dir / "multi_column.pdf",
        tmp_output_dir,
        options=PipelineOptions(),
        force=True,
    )

    got = collected_warnings()
    reset_warnings()
    assert f"UserWarning: {_BBOX}" in got
    captured = capsys.readouterr()
    assert "outside page bounds" not in captured.err
    assert "1 warning(s)" in captured.out


def test_failed_docling_attempt_does_not_count_its_warnings(
    fixture_dir, tmp_output_dir, monkeypatch
):
    """A PDF that falls back to pymupdf4llm keeps only that lane's warnings."""

    def fail(*args, **kwargs):
        _docling_warning(args, kwargs)
        raise RuntimeError("docling broke")

    monkeypatch.setattr(pdf_mod, "has_docling", lambda: True)
    monkeypatch.setattr(pdf_mod, "_extract_via_docling", fail)
    reset_warnings()

    assert pdf_mod.convert_pdf(
        fixture_dir / "multi_column.pdf",
        tmp_output_dir,
        options=PipelineOptions(),
        force=True,
    )

    got = collected_warnings()
    reset_warnings()
    assert not any("outside page bounds" in w for w in got)


def test_docx_warning_fallback_drops_the_discarded_lanes_warnings(
    fixture_dir, tmp_output_dir, monkeypatch, capsys
):
    """After a msword_backend warning, mammoth's output is kept. Python
    warnings and alt-text notes from the thrown-away Docling run must not
    count, while the msword warning that caused the fallback still does."""

    def fake(*args, **kwargs):
        _docling_warning(args, kwargs)
        capture = next(a for a in args if isinstance(a, DoclingWarningCapture))
        capture.note("alt text could not be read")
        return "# Docling output\n", "docling", ["list item dropped"]

    monkeypatch.setattr(docx_mod, "has_docling", lambda: True)
    monkeypatch.setattr(docx_mod, "_extract_via_docling", fake)
    reset_warnings()

    assert docx_mod.convert_docx(
        fixture_dir / "table_heavy.docx", tmp_output_dir, force=True
    )

    got = collected_warnings()
    reset_warnings()
    assert not any("outside page bounds" in w for w in got)
    assert not any("alt text could not be read" in w for w in got)
    assert "docling.msword_backend: list item dropped" in got
    assert "via docling→mammoth" in capsys.readouterr().out
