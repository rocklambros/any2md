"""Tests for T1 — repair_line_wraps."""

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
