"""Tests for ``utils.warn_dropped_document_date``.

The readers return a rejected embedded date instead of printing, and each
converter calls this helper once it knows whether a ``date`` override
replaces the document's own date.
"""

from __future__ import annotations

from any2md.utils import warn_dropped_document_date


def test_warns_with_file_value_and_fallback(capsys):
    warn_dropped_document_date("a.pdf", "D:00000000000000", None)
    err = capsys.readouterr().err
    assert err.startswith("  WARN: a.pdf: ignoring document date 'D:00000000000000'")
    assert "YYYY-MM-DD" in err
    assert "modification time" in err
    assert err.count("\n") == 1


def test_silent_when_a_date_override_replaces_the_document_date(capsys):
    warn_dropped_document_date("a.pdf", "D:00000000000000", {"date": "2025-03-01"})
    assert capsys.readouterr().err == ""


def test_silent_when_nothing_was_rejected(capsys):
    warn_dropped_document_date("a.pdf", None, None)
    assert capsys.readouterr().err == ""


def test_long_values_are_truncated(capsys):
    warn_dropped_document_date("a.docx", "2019-06" + "x" * 900_000, None)
    err = capsys.readouterr().err
    assert len(err) < 300
    assert "900007 chars" in err


def test_hostile_value_stays_on_one_escaped_line(capsys):
    warn_dropped_document_date("a.docx", "x\n  OK: forged\x1b[31m‮", None)
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert "\x1b" not in err
    assert "‮" not in err
