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
