"""Tests for T1 — repair_line_wraps."""

import pytest

from any2md.pipeline import PipelineOptions
from any2md.pipeline.text import repair_line_wraps


def test_joins_wrapped_paragraph():
    text = "This is a paragraph that wraps\nacross two lines.\n"
    out = repair_line_wraps(text, PipelineOptions())
    assert "wraps across two lines" in out


def test_does_not_join_across_blank_line():
    text = "First paragraph\n\nsecond paragraph\n"
    out = repair_line_wraps(text, PipelineOptions())
    assert "First paragraph\n\nsecond" in out


def test_does_not_join_after_terminal_punctuation():
    text = "Sentence one.\nSentence two.\n"
    out = repair_line_wraps(text, PipelineOptions())
    # Both lines end with period; second starts uppercase; no join.
    assert out == "Sentence one.\nSentence two.\n" or out == text


def test_does_not_join_inside_code_block():
    text = "```\nfirst code line\nsecond code line\n```\n"
    out = repair_line_wraps(text, PipelineOptions())
    assert "first code line\nsecond code line" in out  # unchanged


def test_does_not_join_list_items():
    text = "- item one\n- item two\n"
    out = repair_line_wraps(text, PipelineOptions())
    assert out == text


def test_does_not_join_table_rows():
    text = "| A | B |\n| 1 | 2 |\n"
    out = repair_line_wraps(text, PipelineOptions())
    assert out == text


def test_does_not_join_after_heading():
    text = "# Heading\nbody continues\n"
    out = repair_line_wraps(text, PipelineOptions())
    assert "# Heading\nbody continues" in out


def test_spaced_dash_at_line_end_keeps_space():
    # " -" after a space is a dash, not a word break.
    text = "first part -\nsecond part\n"
    out = repair_line_wraps(text, PipelineOptions())
    assert "first part - second part" in out


@pytest.mark.parametrize("rule", ["---", "===", "***", "___", "  -----  "])
def test_setext_underline_and_rules_not_joined(rule):
    text = f"Some heading text\n{rule}\nbody here\n"
    assert repair_line_wraps(text, PipelineOptions()) == text


def test_form_feed_before_fence_does_not_hide_the_opener():
    # The closer must not open a new fence that swallows the prose after it.
    text = "intro\n\f```\ncode\n```\nrest text\nmore"
    out = repair_line_wraps(text, PipelineOptions())
    assert out == "intro\n\f```\ncode\n```\nrest text more"


@pytest.mark.parametrize(
    "second",
    [
        "    ```code``` sits here",  # indented, so not a fence opener
        "```a` b is inline code",  # backtick in the info string
    ],
)
def test_backtick_line_that_is_not_a_fence_still_joins(second):
    # T1 and the block scanner agree on what is a fence line.
    text = f"a wrapped line of prose\n{second}"
    out = repair_line_wraps(text, PipelineOptions())
    assert out == f"a wrapped line of prose {second.lstrip()}"


def test_tilde_fence_is_never_joined():
    text = "a wrapped line of prose\n~~~\ncode\n~~~\nafter"
    assert repair_line_wraps(text, PipelineOptions()) == text
