"""Unit tests for HTML-lane heading-level normalization (v1.2.0).

Many CMS templates mark body sections as H3 or H4 under a page H1, so
once the H1 is restored the body skips levels (h1 -> h3). The helper
re-ranks headings by section depth: siblings stay siblings, nesting is
kept, and the shallowest body level becomes H2.
"""

from __future__ import annotations

import re

import pytest

from any2md.converters.html import _normalize_heading_levels


def _levels(md: str) -> list[int]:
    return [len(m) for m in re.findall(r"^(#{1,6}) ", md, re.MULTILINE)]


@pytest.mark.parametrize(
    "before, after",
    [
        ([1, 3, 3, 3], [1, 2, 2, 2]),  # all sections one level too deep
        ([1, 4, 4], [1, 2, 2]),
        ([1, 3, 4, 3], [1, 2, 3, 2]),  # nesting under H3 preserved
        ([1, 3, 2, 3], [1, 2, 2, 3]),  # lead-in H3 before the first H2
        ([1, 2, 4], [1, 2, 3]),  # in-body skip
        ([1, 2, 2, 3], [1, 2, 2, 3]),  # already clean: unchanged
        ([1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6]),
    ],
)
def test_levels_reranked(before, after):
    body = "\n\n".join("#" * lv + f" H{i}" for i, lv in enumerate(before)) + "\n"
    assert _levels(_normalize_heading_levels(body)) == after


def test_clean_body_returned_byte_identical():
    body = "# T\n\nIntro.\n\n## A\n\nText.\n\n### A.1\n\nMore.\n"
    assert _normalize_heading_levels(body) == body


def test_only_hash_prefix_changes():
    body = "# T\n\n### Section  with  spacing ###\n\nText.\n"
    out = _normalize_heading_levels(body)
    assert out == "# T\n\n## Section  with  spacing ###\n\nText.\n"


def test_headings_inside_fenced_code_untouched():
    body = "# T\n\n```\n### not a heading\n```\n\n### Real\n"
    out = _normalize_heading_levels(body)
    assert "### not a heading" in out
    assert "\n## Real\n" in out


def test_heading_before_h1_keeps_level_below_h1():
    # Never promote anything to H1: that would create a second H1.
    body = "### Kicker\n\n# T\n\n### Section\n"
    out = _normalize_heading_levels(body)
    assert _levels(out) == [2, 1, 2]


def test_no_headings_is_noop():
    body = "Just prose.\n\nMore prose.\n"
    assert _normalize_heading_levels(body) == body


def test_idempotent():
    body = "# T\n\n### A\n\n#### A.1\n\n### B\n"
    once = _normalize_heading_levels(body)
    assert _normalize_heading_levels(once) == once
