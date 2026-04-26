"""Tests for C5 — collapse_whitespace."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.cleanup import collapse_whitespace


def test_collapses_runs_of_spaces():
    assert collapse_whitespace("foo    bar", PipelineOptions()) == "foo bar"


def test_collapses_tabs_to_single_space():
    assert collapse_whitespace("foo\t\tbar", PipelineOptions()) == "foo bar"


def test_strips_trailing_whitespace_per_line():
    assert collapse_whitespace("foo  \nbar  \n", PipelineOptions()) == "foo\nbar\n"


def test_collapses_three_plus_blank_lines_to_two():
    text = "alpha\n\n\n\nbeta"
    assert collapse_whitespace(text, PipelineOptions()) == "alpha\n\nbeta"


def test_preserves_single_blank_line():
    text = "alpha\n\nbeta"
    assert collapse_whitespace(text, PipelineOptions()) == "alpha\n\nbeta"


def test_preserves_indentation_inside_code_blocks():
    # Naive collapse would damage indentation. We only collapse runs of
    # whitespace inside a line, but leading whitespace (indent) is preserved
    # by re only matching 2+ spaces with one or more chars on each side.
    # However our spec for C5 collapses inline runs; leading whitespace in
    # code blocks is rare in pipeline input (Docling/markdownify use fenced
    # blocks already). For Phase 1 we collapse runs >= 2 in body text.
    text = "    indented line"
    # Leading runs are NOT collapsed — only inter-word runs.
    assert collapse_whitespace(text, PipelineOptions()) == "    indented line"
