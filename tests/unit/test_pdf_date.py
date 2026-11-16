"""Tests for ``converters.pdf._parse_pdf_date``.

The emitted ``date`` must be ``YYYY-MM-DD`` in ASCII digits. PDF dates
written with other Unicode digits are dropped, so the caller falls back
to the file's modification time instead of emitting a non-conforming date.
"""

from __future__ import annotations

import pytest

from any2md.converters.pdf import _parse_pdf_date


def test_parses_standard_pdf_date():
    assert _parse_pdf_date("D:20250315120000Z") == "2025-03-15"


@pytest.mark.parametrize(
    "raw",
    [
        "D:\u00b2\u2070\u00b2\u2075" + "0315",  # superscript digits
        "D:\u0662\u0660\u0662\u0665\u0660\u0663\u0661\u0665",  # Arabic-Indic
    ],
)
def test_non_ascii_digits_yield_no_date(raw):
    assert _parse_pdf_date(raw) is None


@pytest.mark.parametrize("raw", ["D:00000000000000", "D:20259999", "D:20250230"])
def test_impossible_calendar_dates_yield_no_date(raw):
    assert _parse_pdf_date(raw) is None


class _FakeDoc:
    def __init__(self, creation_date):
        self.metadata = {"creationDate": creation_date}


def test_rejected_creation_date_is_returned_not_printed(capsys):
    from any2md.converters.pdf import _parse_pdf_metadata

    props = _parse_pdf_metadata(_FakeDoc("D:00000000000000"))
    assert props["date"] is None
    assert props["date_rejected"] == "D:00000000000000"
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("raw", ["D:20250315120000+01'00'", "", None, "D:", "  D:  "])
def test_valid_or_absent_creation_date_rejects_nothing(raw):
    from any2md.converters.pdf import _parse_pdf_metadata

    assert _parse_pdf_metadata(_FakeDoc(raw))["date_rejected"] is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" D:20250315120000Z", "2025-03-15"),  # leading whitespace
        ("2019-06-05T12:00:00Z", "2019-06-05"),  # ISO form some producers write
        ("D:2019-06-05", "2019-06-05"),
    ],
)
def test_parses_whitespace_and_iso_forms(raw, expected):
    assert _parse_pdf_date(raw) == expected
