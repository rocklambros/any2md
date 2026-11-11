"""Setext underlines in text-lane output are rule artifacts, not headings.

Every text-lane backend writes real headings in ATX form (markdownify
runs with ``heading_style="ATX"``, pymupdf4llm emits ``#`` lines, and the
TXT structurizer rewrites underlined headings itself). A ``---`` or
``===`` line glued to a paragraph comes from a rule or a run of ``=`` in
the source, yet a Markdown renderer would show the paragraph as a
heading and C7 would count it. T11 separates the underline so the final
Markdown renders what the source showed, and C7 reports that.
"""

from any2md.pipeline import PipelineOptions, run
from any2md.pipeline.blocks import find_headings
from any2md.pipeline.text import split_setext_artifacts


def test_dash_rule_after_paragraph_becomes_a_thematic_break():
    text = "# Title\n\nSome paragraph line\n---\n\nMore text.\n"
    out = split_setext_artifacts(text, PipelineOptions())
    assert out == "# Title\n\nSome paragraph line\n\n---\n\nMore text.\n"
    assert [level for _, _, level in find_headings(out)] == [1]


def test_equals_run_after_paragraph_stays_literal_text():
    text = "# Title\n\nSome paragraph line\n=====\n"
    out = split_setext_artifacts(text, PipelineOptions())
    assert out == "# Title\n\nSome paragraph line\n\n=====\n"
    assert [level for _, _, level in find_headings(out)] == [1]


def test_multi_line_paragraph_keeps_its_lines_together():
    text = "# T\n\nfirst line\nsecond line\n---\n"
    out = split_setext_artifacts(text, PipelineOptions())
    assert out == "# T\n\nfirst line\nsecond line\n\n---\n"


def test_text_without_setext_is_unchanged():
    text = "# Title\n\nBody.\n\n---\n\nMore.\n"
    assert split_setext_artifacts(text, PipelineOptions()) == text


def test_fenced_underline_is_unchanged():
    text = "# T\n\n```\nline\n---\n```\n"
    assert split_setext_artifacts(text, PipelineOptions()) == text


def test_text_lane_adds_no_heading_warnings_for_rule_artifacts():
    text = "# Title\n\nIntro paragraph\n---\n\nBody line\n===\n\n## Section\n\nEnd.\n"
    _, warnings = run(text, "text", PipelineOptions())
    assert warnings == []


def test_text_lane_strict_passes_on_rule_artifacts():
    text = "# Title\n\nIntro paragraph\n---\n\nBody.\n"
    _, warnings = run(text, "text", PipelineOptions(strict=True))
    assert warnings == []


def test_structured_lane_still_ranks_setext_headings():
    # S4 rewrites a setext heading as ATX, so C7 sees it as a heading.
    text = "Title\n=====\n\nSub\n---\n\nBody.\n"
    out, warnings = run(text, "structured", PipelineOptions())
    assert "# Title" in out and "## Sub" in out
    assert warnings == []
