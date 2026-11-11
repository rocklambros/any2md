"""Tests for the shared block scanner used by S4 and the HTML lane."""

import pytest

from any2md.pipeline.blocks import (
    fence_runs,
    fenced_lines,
    find_headings,
    protected_lines,
)


def _flags(text: str) -> list[bool]:
    return list(fenced_lines(text))


def _protected(text: str) -> list[bool]:
    return protected_lines(text)


# protected_lines covers fenced code and raw HTML blocks.


def test_protected_covers_fenced_code():
    assert _protected("a\n```\n# x\n```\nb") == [False, True, True, True, False]


@pytest.mark.parametrize(
    "start, end",
    [("<pre>", "</pre>"), ("<!--", "-->"), ("<?x", "?>"), ("<![CDATA[", "]]>")],
)
def test_protected_covers_html_types_1_to_5_through_blank_lines(start, end):
    text = f"{start}\n# x\n\n# y\n{end}\n# z"
    assert _protected(text) == [True, True, True, True, True, False]


def test_protected_covers_html_block_ending_on_start_line():
    assert _protected("<pre>x</pre>\n# z") == [True, False]


@pytest.mark.parametrize("start", ["<div>", "<span>"])
def test_protected_html_types_6_and_7_end_at_blank_line(start):
    assert _protected(f"{start}\n# x\n\n# y") == [True, True, False, False]


def test_protected_html_block_in_list_item_ends_with_item():
    assert _protected("- <pre>\n  # x\n# y") == [True, True, False]


def test_fenced_lines_does_not_flag_html_blocks():
    assert _flags("<pre>\n# x\n</pre>") == [False, False, False]


def test_plain_fence_flags_fence_and_body():
    assert _flags("a\n```py\nx\n```\nb") == [False, True, True, True, False]


def test_longer_closer_closes():
    assert _flags("```\nx\n`````\nb") == [True, True, True, False]


def test_shorter_closer_does_not_close():
    assert _flags("````\n```\nx") == [True, True, True]


def test_closer_with_trailing_whitespace_closes():
    assert _flags("~~~\nx\n~~~  \t\nb") == [True, True, True, False]


@pytest.mark.parametrize("indent", [1, 2, 3])
def test_top_level_fence_indented_up_to_three(indent):
    pad = " " * indent
    assert _flags(f"{pad}```\nx\n{pad}```\nb") == [True, True, True, False]


def test_top_level_four_space_indent_is_code_not_fence():
    assert _flags("    ```\nx\n    ```") == [False, False, False]


def test_tab_indent_is_code_not_fence():
    assert _flags("\t```\nx") == [False, False]


@pytest.mark.parametrize(
    "marker, fence_indent",
    [("-", 2), ("*", 5), ("+", 4), ("1.", 3), ("1.", 6), ("10)", 4), ("10)", 7)],
)
def test_fence_inside_list_item(marker, fence_indent):
    pad = " " * fence_indent
    text = f"{marker} item\n\n{pad}```\n{pad}x\n{pad}```\nafter"
    assert _flags(text) == [False, False, True, True, True, False]


def test_fence_too_deep_inside_list_item_is_code():
    # Content column is 2, so indent 6 is indented code inside the item.
    assert _flags("- item\n\n      ```\nx") == [False, False, False, False]


def test_fence_inside_nested_list_item():
    text = "1. a\n   - b\n\n        ```\n        x\n        ```"
    assert _flags(text) == [False, False, False, True, True, True]


def test_lazy_paragraph_line_keeps_list_item_open():
    # "para" is a lazy continuation of the item's paragraph, so the item
    # stays open and the 4-space fence after the blank line sits inside it.
    assert _flags("- item\npara\n\n    ```\nx") == [False, False, False, True, False]


def test_unindented_heading_ends_list_context():
    # A heading is not paragraph text, so it ends the list.
    assert _flags("- item\n# H\n\n    ```\nx") == [False] * 5


def test_fence_on_list_marker_line():
    assert _flags("- ```\n  x\n  ```\nb") == [True, True, True, False]


def test_unclosed_fence_runs_to_end():
    assert _flags("```\nx\ny") == [True, True, True]


def test_fence_one_column_past_nested_item_limit_is_code():
    # "- b" has content column 5, so indent 9 is four past it.
    assert _flags("1. a\n   - b\n\n         ```\nx") == [False] * 5


@pytest.mark.parametrize("brk", ["* * *", "- - -", "***", "___", "-\t-\t-", "_ _ _ _"])
def test_thematic_break_is_not_a_list_item(brk):
    # A list item would make the 4-space line a fence inside the item.
    assert _flags(f"{brk}\n\n    ```\nx") == [False] * 4


def test_mixed_characters_are_not_a_thematic_break():
    # "- * -" is a list item holding a list item, so the fence is inside.
    assert _flags("- * -\n\n    ```\n    x") == [False, False, True, True]


def test_list_fence_ends_when_item_ends():
    assert _flags("- ```\n  code\n\n### Real\n```") == [
        True,
        True,
        True,
        False,
        True,
    ]


def test_nested_list_fence_ends_when_inner_item_ends():
    text = "1. a\n   - ```\n     code\n   tail\n   ```"
    assert _flags(text) == [False, True, True, False, True]


def test_top_level_fence_ignores_dedent():
    assert _flags("  ```\nx\n  ```\nb") == [True, True, True, False]


@pytest.mark.parametrize("markers", ["- - ", "1. - ", "* 2) "])
def test_several_markers_on_one_line(markers):
    width = len(markers)
    pad = " " * width
    text = f"{markers}```\n{pad}code\n{pad}```\nafter"
    assert _flags(text) == [True, True, True, False]


def test_marker_line_ending_in_thematic_break_holds_no_fence():
    assert _flags("- * * *\n  ```\n  x") == [False, True, True]


def test_marker_after_five_spaces_is_code_not_a_nested_item():
    # Five spaces after "-" make "- ```" indented code inside the item.
    assert _flags("-     - ```\nx") == [False, False]


def test_long_marker_run_is_linear():
    # A quadratic marker loop takes seconds here. The bound is generous.
    import time

    line = "- " * 200_000 + "x"
    start = time.perf_counter()
    assert _flags(line) == [False]
    assert time.perf_counter() - start < 2.0


# Tabs expand to 4-column stops before markers and indents are measured.


@pytest.mark.parametrize("item", ["- \titem", "-\titem", "1.\titem"])
def test_tab_after_marker_moves_content_column(item):
    # Content column 4, so the 2-space fence is top level and holds "x".
    assert _flags(f"{item}\n\n  ```\nx\n```") == [False, False, True, True, True]


def test_tab_indented_fence_inside_list_item():
    text = "- a\n\n\t```\n\tx\n\t```\nb"
    assert _flags(text) == [False, False, True, True, True, False]


# Paragraph interruption: only a non-empty item, starting at 1 when
# ordered, may interrupt a paragraph.


def test_ordered_marker_past_one_is_paragraph_text():
    text = "Paragraph\n2. not a list\n\n   ```\nx"
    assert _flags(text) == [False, False, False, True, True]


@pytest.mark.parametrize("marker", ["1.", "1)", "01.", "-", "*"])
def test_marker_that_may_interrupt_opens_an_item(marker):
    # The item's content column is the fence base, so "x" at column 0
    # ends the item and its fence.
    pad = " " * (len(marker) + 1)
    text = f"Paragraph\n{marker} item\n\n{pad}```\nx"
    assert _flags(text) == [False, False, False, True, False]


def test_empty_item_does_not_interrupt_paragraph():
    assert _flags("Paragraph\n-\n\n  ```\nx") == [False, False, False, True, True]


def test_ordered_marker_past_one_starts_list_after_blank_line():
    text = "Paragraph\n\n2. item\n\n   ```\nx"
    assert _flags(text) == [False, False, False, False, True, False]


def test_heading_ends_paragraph():
    text = "Paragraph\n## Head\n2. item\n\n   ```\nx"
    assert _flags(text) == [False, False, False, False, True, False]


# Closers allow only spaces, tabs, and a terminal carriage return.


def test_nbsp_after_closer_does_not_close():
    assert _flags("```\n```\u00a0\nx\n```\nb") == [True, True, True, True, False]


def test_crlf_closer_closes():
    assert _flags("```\r\nx\r\n``` \t\r\nb") == [True, True, True, False]


def test_carriage_return_before_text_does_not_close():
    assert _flags("```\n```\rx\ny") == [True, True, True]


# Raw HTML blocks (CommonMark 4.6): fence lines inside are not openers.


@pytest.mark.parametrize(
    "start, end",
    [
        ("<pre>", "</pre>"),
        ("<script>", "</script>"),
        ("<STYLE type='x'>", "</style>"),
        ("<textarea", "</TEXTAREA>"),
        ("<!-- note", "-->"),
        ("<?xml", "?>"),
        ("<!DOCTYPE", ">"),
        ("<![CDATA[", "]]>"),
    ],
)
def test_html_block_types_1_to_5_hide_fences(start, end):
    # Types 1 to 5 run through blank lines to their end marker.
    text = f"{start}\n\n```\n{end}\n```\nx"
    assert _flags(text) == [False, False, False, False, True, True]


def test_html_block_ends_on_its_start_line():
    assert _flags("<pre>x</pre>\n```\nx") == [False, True, True]


def test_raw_tag_name_needs_a_boundary():
    # "<prefix>" is a type 7 block, which a blank line ends.
    assert _flags("<prefix>\n\n```\nx") == [False, False, True, True]


@pytest.mark.parametrize("start", ['<div class="a">', "</table>", "<hr/>", "<P"])
def test_html_block_type_6_ends_at_blank_line(start):
    assert _flags(f"{start}\n```\n\n```\nx") == [False, False, False, True, True]


@pytest.mark.parametrize(
    "start", ["<span>", "</span>", "<my-tag a='1' b=c d>", '<x data-a="q > r"/>']
)
def test_html_block_type_7_ends_at_blank_line(start):
    assert _flags(f"{start}\n```\n\n```\nx") == [False, False, False, True, True]


@pytest.mark.parametrize("line", ["<span> text", "<span", "<a b=>", "</pre>"])
def test_incomplete_or_trailing_tag_is_not_type_7(line):
    assert _flags(f"{line}\n```\nx") == [False, True, True]


def test_type_7_does_not_interrupt_paragraph():
    assert _flags("Paragraph\n<span>\n```\nx") == [False, False, True, True]


def test_type_6_interrupts_paragraph():
    assert _flags("Paragraph\n<div>\n```\nx") == [False, False, False, False]


def test_html_block_inside_list_item():
    assert _flags("- <pre>\n  ```\n  </pre>\nb") == [False, False, False, False]


def test_html_block_in_list_item_ends_with_item():
    assert _flags("- <pre>\n  x\n```\ny") == [False, False, True, True]


def test_long_attribute_list_is_linear():
    import time

    line = "<a " + "b='c' " * 100_000 + ">"
    start = time.perf_counter()
    assert _flags(f"{line}\n```\nx") == [False, False, False]
    assert time.perf_counter() - start < 2.0


# Block quotes: a ">" prefix opens a container that fences, HTML blocks,
# list items, and headings can sit inside.


def test_quoted_lines_are_protected():
    # A quoted heading is quoted content, never a document heading.
    assert _protected("a\n\n> # x\n> text\n\nb") == [
        False,
        False,
        True,
        True,
        False,
        False,
    ]


def test_blank_line_ends_quote():
    assert _protected("> # x\n\n# y") == [True, False, False]


def test_fence_inside_quote():
    assert _flags("> ```\n> # x\n> ```\nb") == [True, True, True, False]


def test_quote_prefix_without_space_and_indented_marker():
    assert _flags(">```\n   >x\n>```\nb") == [True, True, True, False]


def test_fence_inside_quote_ends_with_quote():
    # The quote ends at the line with no ">", so its fence ends too and
    # "```" there opens a new top-level fence.
    assert _flags("> ```\n> x\n```\ny") == [True, True, True, True]


def test_blank_line_ends_quote_and_its_fence():
    assert _flags("> ```\n\n```\nx") == [True, False, True, True]


def test_fence_does_not_take_lazy_continuation():
    # "x" lacks ">", and lazy continuation never extends a fence.
    assert _flags("> ```\nx\n```") == [True, False, True]


def test_html_block_inside_quote_ends_with_quote():
    assert _protected("> <pre>\n> # x\n# y") == [True, True, False]


def test_nested_quotes():
    assert _flags("> > ```\n> > x\n> y\n```") == [True, True, False, True]


def test_list_item_inside_quote():
    text = "> - a\n>\n>     ```\n>     x\n>     ```\nb"
    assert _flags(text) == [False, False, True, True, True, False]


def test_quote_inside_list_item():
    text = "- > ```\n  > x\n  > ```\nb"
    assert _flags(text) == [True, True, True, False]


def test_quote_four_space_indent_is_code():
    assert _protected("    > # x") == [False]


def test_long_quote_run_is_linear():
    import time

    text = "> " * 200_000 + "x\n" + ">" * 200_000 + "\n" + "\n" * 1000 + "y"
    start = time.perf_counter()
    flags = _protected(text)
    assert flags[:2] == [True, True] and flags[-1] is False
    assert time.perf_counter() - start < 2.0


def test_deep_list_then_blank_lines_is_linear():
    import time

    text = "- " * 100_000 + "x" + "\n" * 100_000 + "> y"
    start = time.perf_counter()
    assert _protected(text)[-1] is True
    assert time.perf_counter() - start < 2.0


# Lazy continuation: a paragraph line may drop the ">" or the list
# indent and still belong to the paragraph.


def test_lazy_line_stays_in_quote():
    # "b" continues the quoted paragraph, so it is quoted content.
    assert _protected("> a\nb\n\nc") == [True, True, False, False]


def test_lazy_line_in_nested_quote():
    assert _protected("> > a\n> b\nc\n\nd") == [True, True, True, False, False]


def test_lazy_line_keeps_quote_open_for_fence():
    assert _flags("> a\nb\n> ```\n> x") == [False, False, True, True]


def test_heading_after_quote_is_not_lazy():
    assert _protected("> a\n# b") == [True, False]


def test_thematic_break_after_quote_is_not_lazy():
    assert _protected("> a\n---\nb") == [True, False, False]


def test_fence_after_quote_is_not_lazy():
    assert _flags("> a\n```\nx") == [False, True, True]


def test_lazy_line_after_heading_is_not_continuation():
    # The quote holds a heading, not a paragraph, so "b" ends the quote.
    assert _protected("> # a\nb") == [True, False]


def test_indented_lazy_line_is_continuation():
    assert _protected("> a\n    b") == [True, True]


def test_lazy_line_in_list_keeps_item_open():
    assert _flags("- a\nb\n  ```\n  x") == [False, False, True, True]


def test_lazy_marker_that_cannot_interrupt_starts_a_list():
    # The item is not matched, so "2." is a new list, not lazy text.
    assert _flags("- a\n2. b\n\n   ```\nx") == [False, False, False, True, False]


# Setext headings: a paragraph followed by a "=" or "-" underline.


def _headings(text: str) -> list[tuple[int, int, int]]:
    return find_headings(text)


def test_setext_h1_and_h2():
    assert _headings("Title\n=====\n\nSub\n---") == [(0, 1, 1), (3, 4, 2)]


def test_setext_multiline_paragraph():
    assert _headings("a\nb\n===") == [(0, 2, 1)]


def test_setext_underline_indent_and_trailing_space():
    assert _headings("a\n   ==  \t") == [(0, 1, 1)]


def test_setext_underline_four_spaces_is_text():
    assert _headings("a\n    ===") == []


def test_dash_after_blank_line_is_thematic_break():
    assert _headings("a\n\n---") == []


def test_setext_wins_over_empty_list_item():
    assert _headings("a\n-") == [(0, 1, 2)]


def test_spaced_dashes_are_a_thematic_break():
    assert _headings("a\n- - -") == []


def test_equals_with_inner_space_is_text():
    assert _headings("a\n= =") == []


def test_setext_after_atx_is_text():
    assert _headings("# a\n===") == [(0, 0, 1)]


def test_setext_mixed_with_atx_in_order():
    assert _headings("# T\n\nA\n---\n\n### B") == [(0, 0, 1), (2, 3, 2), (5, 5, 3)]


def test_setext_inside_quote_is_not_a_document_heading():
    assert _headings("> a\n> ---") == []


def test_setext_underline_is_not_lazy():
    # "---" lacks ">", cannot be a lazy line, and so is a thematic break.
    assert _headings("> a\n---") == []
    assert _headings("> a\n===") == []


def test_setext_inside_list_item_is_not_a_document_heading():
    assert _headings("- a\n  ---") == []


def test_list_item_underline_after_paragraph_in_item():
    # "  ---" inside the item is a setext underline, so it is not a list.
    assert _flags("- a\n  ---\n\n    ```\nx") == [False, False, False, True, False]


def test_headings_skip_fenced_and_quoted_lines():
    assert _headings("```\n# x\n```\n> # y\n## z") == [(4, 4, 2)]


def test_long_underline_run_is_linear():
    import time

    text = "a\n" + "=" * 400_000 + "\nb\n" + "-" * 400_000 + " x"
    start = time.perf_counter()
    assert _headings(text) == [(0, 1, 1)]
    assert time.perf_counter() - start < 2.0


def test_empty_list_item_ends_at_blank_line():
    # An item may not open with a blank line, so "  ```" is top level.
    assert _flags("-\n\n  ```\nx") == [False, False, True, True]


# Form feed and vertical tab: extractors put "\f" at page breaks, often
# right before a block marker. The scanner reads both as zero width, so
# the marker after them still counts.


@pytest.mark.parametrize("sep", ["\f", "\v", "\f\v"])
def test_separator_before_fence_opener(sep):
    text = f"intro\n{sep}```\ncode\n```\nrest text\nmore"
    assert _flags(text) == [False, True, True, True, False, False]


def test_separator_before_fence_closer():
    assert _flags("```\ncode\n\f```\nrest") == [True, True, True, False]


def test_separator_before_quote_marker():
    assert _protected("\f> # x\n\nb") == [True, False, False]


def test_separator_before_list_marker():
    assert _flags("\f- ```\n  x\n  ```\nb") == [True, True, True, False]


def test_separator_only_line_is_blank():
    # A blank line ends the quote, so "b" is not lazy quoted text.
    assert _protected("> a\n\f\nb") == [True, False, False]


def test_separator_before_atx_heading():
    assert _headings("\f# Title\ntext") == [(0, 0, 1)]


def test_separator_before_setext_underline():
    assert _headings("Title\n\f===") == [(0, 1, 1)]


def test_separator_mid_line_does_not_shift_indent():
    # "\f" is zero width, so the fence still sits at column 3.
    assert _flags("   \f```\nx\n```") == [True, True, True]


@pytest.mark.parametrize(
    "flags, runs",
    [
        ([], []),
        ([False], [(False, 0, 1)]),
        ([True, True], [(True, 0, 2)]),
        (
            [False, True, True, False, False],
            [(False, 0, 1), (True, 1, 3), (False, 3, 5)],
        ),
    ],
)
def test_fence_runs_cover_every_line_in_order(flags, runs):
    assert list(fence_runs(flags)) == runs


def test_scan_runs_once_per_distinct_text(monkeypatch):
    from any2md.pipeline import blocks

    calls = []
    real = blocks._scan_blocks

    def counting(lines):
        calls.append(len(lines))
        return real(lines)

    monkeypatch.setattr(blocks, "_scan_blocks", counting)
    blocks._scan_text.cache_clear()
    text = "a\n```\nx\n```\n# h"
    same = "".join(list(text))  # equal text, different object
    assert same is not text
    fenced_lines(text)
    fenced_lines(same)
    find_headings(same)
    protected_lines(text)
    assert len(calls) == 1
    fenced_lines(text + "\nmore")
    assert len(calls) == 2
    blocks._scan_text.cache_clear()


def test_cached_flags_are_immutable():
    assert isinstance(fenced_lines("```\nx\n```"), tuple)
