"""Tests for the shared fence scanner used by S4 and the HTML lane."""

import pytest

from any2md.pipeline.structured import fenced_lines


def _flags(text: str) -> list[bool]:
    return fenced_lines(text.split("\n"))


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


def test_unindented_paragraph_ends_list_context():
    # "para" ends the list, so a 4-space fence after it is indented code.
    assert _flags("- item\npara\n\n    ```\nx") == [False] * 5


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
