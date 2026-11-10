"""Unit tests for the HTML-lane H1 guarantee (v1.2.0).

trafilatura keeps a page ``<h1>`` only when it sits inside the content
node it selects. Hero banners and ``<header>`` blocks outside that node
lose their ``<h1>``, so the body reached the C7 validator without one.
``_visible_h1`` recovers the page heading from the raw HTML and
``_ensure_h1`` writes it back into the body exactly once.
"""

from __future__ import annotations

import pytest

from any2md.converters.html import _ensure_h1, _visible_h1


# ---------- _visible_h1 ----------


def test_visible_h1_returns_single_h1_text():
    html = "<html><body><header><h1>Page Title</h1></header><p>x</p></body></html>"
    assert _visible_h1(html) == "Page Title"


def test_visible_h1_flattens_nested_markup_and_entities():
    html = "<h1>Join Zenity&#x27;s <em>&quot;Prompt Jar&quot;</em>\n  Contest</h1>"
    assert _visible_h1(html) == 'Join Zenity\'s "Prompt Jar" Contest'


def test_visible_h1_none_when_page_has_no_h1():
    assert _visible_h1("<html><body><p>no heading</p></body></html>") is None


def test_visible_h1_none_when_page_has_several_h1s():
    # Ambiguous: we can't tell which one is the document title.
    assert _visible_h1("<h1>One</h1><p>x</p><h1>Two</h1>") is None


def test_visible_h1_ignores_empty_h1_when_counting():
    # Decorative empty <h1> wrappers (logos, icons) are common in site
    # chrome and must not block the real heading.
    assert _visible_h1("<h1><img src='logo.svg'></h1><h1>Real</h1>") == "Real"


# ---------- _ensure_h1 ----------


def test_inserts_h1_when_body_has_none():
    body = "First paragraph.\n\n## Section\n\nMore.\n"
    assert _ensure_h1(body, "The Title") == (
        "# The Title\n\nFirst paragraph.\n\n## Section\n\nMore.\n"
    )


def test_insert_drops_leading_blank_lines():
    assert _ensure_h1("\n\nBody.\n", "T") == "# T\n\nBody.\n"


def test_existing_h1_left_untouched():
    body = "# Already Here\n\nBody.\n"
    assert _ensure_h1(body, "Different Title") == body


def test_h1_inside_fenced_code_does_not_count():
    body = "```\n# comment in code\n```\n\nBody.\n"
    out = _ensure_h1(body, "Real Title")
    assert out.startswith("# Real Title\n\n```")


@pytest.mark.parametrize(
    "first_line",
    [
        "The Title",
        "**The Title**",
        "__The Title__",
        "*The Title*",
        "***The Title***",
        "  **The Title**  ",
        "**The  Title**",
    ],
)
def test_first_line_repeating_title_is_promoted(first_line):
    body = f"{first_line}\n\nBody paragraph.\n"
    out = _ensure_h1(body, "The Title")
    assert out == "# The Title\n\nBody paragraph.\n"


def test_promoted_line_keeps_its_own_text():
    # Case differs from the title string: promote the page's own text.
    out = _ensure_h1("**the title**\n\nBody.\n", "The Title")
    assert out.startswith("# the title\n")


def test_non_matching_first_line_is_not_promoted():
    body = "**Exciting News!** Something happened.\n\nMore.\n"
    out = _ensure_h1(body, "Exciting News")
    assert out == "# Exciting News\n\n" + body


@pytest.mark.parametrize("title", [None, "", "   ", "\n\t"])
def test_no_title_leaves_body_unchanged(title):
    body = "Body without heading.\n"
    assert _ensure_h1(body, title) == body


def test_title_whitespace_collapsed_to_one_line():
    out = _ensure_h1("Body.\n", "  Multi\nLine\t Title  ")
    assert out.startswith("# Multi Line Title\n\n")


def test_empty_body_gets_heading_only():
    assert _ensure_h1("", "T") == "# T\n"


def test_deterministic():
    body = "Para.\n\n## S\n"
    assert _ensure_h1(body, "T") == _ensure_h1(body, "T")


def test_h1_inside_html_comment_does_not_count():
    body = "<!--\n# commented out\n-->\n\nBody.\n"
    out = _ensure_h1(body, "Real Title")
    assert out == "# Real Title\n\n" + body


def test_h1_inside_pre_block_does_not_count():
    body = "<pre>\n# shell prompt\n</pre>\n\nBody.\n"
    out = _ensure_h1(body, "Real Title")
    assert out == "# Real Title\n\n" + body


def test_h1_after_div_block_blank_line_counts():
    body = "<div>\n\n# Real H1\n\nBody.\n"
    assert _ensure_h1(body, "Other Title") == body
