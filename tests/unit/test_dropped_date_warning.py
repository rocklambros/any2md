"""Tests for ``utils.warn_dropped_document_date``.

The readers return a rejected embedded date instead of printing, and each
converter calls this helper once it knows whether a ``date`` override
replaces the document's own date.
"""

from __future__ import annotations

import pytest

from any2md.pipeline import PipelineOptions
from any2md.utils import warn_dropped_document_date


def test_warns_with_file_value_and_fallback(capsys):
    warn_dropped_document_date("a.pdf", "D:00000000000000", PipelineOptions())
    err = capsys.readouterr().err
    assert err.startswith("  WARN: a.pdf: ignoring document date 'D:00000000000000'")
    assert "not a full YYYY-MM-DD calendar date" in err
    assert "modification time" in err
    assert err.count("\n") == 1


def test_silent_when_a_date_override_replaces_the_document_date(capsys):
    warn_dropped_document_date(
        "a.pdf",
        "D:00000000000000",
        PipelineOptions(frontmatter_overrides={"date": "2025-03-01"}),
    )
    assert capsys.readouterr().err == ""


def test_silent_when_nothing_was_rejected(capsys):
    warn_dropped_document_date("a.pdf", None, PipelineOptions())
    assert capsys.readouterr().err == ""


def test_long_values_are_truncated_outside_the_quotes(capsys):
    value = "2019-06" + "x" * 900_000
    warn_dropped_document_date("a.docx", value, PipelineOptions())
    err = capsys.readouterr().err
    assert len(err) < 300
    assert f"{value[:80]!r}... (900007 chars)" in err


def test_hostile_value_stays_on_one_escaped_line(capsys):
    warn_dropped_document_date("a.docx", "x\n  OK: forged\x1b[31m‮", PipelineOptions())
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert "\x1b" not in err
    assert "‮" not in err


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_date_override_warning_says_date_is_left_blank(capsys, blank):
    """A blank override is still merged, so date ends up blank, not mtime."""
    warn_dropped_document_date(
        "a.pdf",
        "D:00000000000000",
        PipelineOptions(frontmatter_overrides={"date": blank}),
    )
    err = capsys.readouterr().err
    assert "ignoring document date" in err
    assert "blank" in err
    assert "modification time" not in err


def test_null_date_override_warning_says_date_is_left_blank(capsys):
    warn_dropped_document_date(
        "a.pdf",
        "D:00000000000000",
        PipelineOptions(frontmatter_overrides={"date": None}),
    )
    err = capsys.readouterr().err
    assert "blank" in err
    assert "modification time" not in err


def test_blank_override_with_auto_id_leaves_the_explanation_to_compose(capsys):
    """compose() fails the file on the blank date, so do not claim it stays blank."""
    opts = PipelineOptions(auto_id=True, frontmatter_overrides={"date": ""})
    warn_dropped_document_date("a.docx", "2019-06", opts)
    assert capsys.readouterr().err == ""


def test_blank_override_with_auto_id_and_explicit_id_still_says_blank(capsys):
    opts = PipelineOptions(
        auto_id=True, frontmatter_overrides={"date": "", "document_id": "X-1"}
    )
    warn_dropped_document_date("a.docx", "2019-06", opts)
    assert "leaves date blank" in capsys.readouterr().err
