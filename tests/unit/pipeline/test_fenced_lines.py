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
