"""Tests for ``utils.clean_iso_date``, the shared extractor date check."""

from __future__ import annotations

import pytest

from any2md.utils import clean_iso_date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2025-03-01", "2025-03-01"),
        ("  2025-03-01\n", "2025-03-01"),
        ("2024-02-29", "2024-02-29"),
    ],
)
def test_accepts_ascii_calendar_dates(raw, expected):
    assert clean_iso_date(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "0000-00-00",
        "2025-99-99",
        "2023-02-29",
        "20250301",
        "2025/03/01",
        "٢٠٢٥-٠٣-٠١",
        "2025-03-01T00",
        None,
    ],
)
def test_rejects_everything_else(raw):
    assert clean_iso_date(raw) is None
