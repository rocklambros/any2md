"""Regression tests for v1.0.3 lane-agnostic body cleanup.

In v1.0.2, T7 dedupe_toc_table, T8 strip_cover_artifacts, and T9
strip_repeated_byline were registered only in text.STAGES. Docling
output uses lane="structured", so these stages never fired on it
even when the patterns they catch were present in the body.

v1.0.3 adds them to structured.STAGES too. T10 strip_web_fragments
correctly stays text-lane-only (trafilatura-specific patterns).
"""

from any2md.pipeline import PipelineOptions, run
from any2md.pipeline import structured, text


def _stage_names(stages: list) -> list[str]:
    return [s.__name__ for s in stages]


def test_structured_stages_now_include_t7_t8_t9():
    names = _stage_names(structured.STAGES)
    assert "strip_repeated_byline" in names
    assert "dedupe_toc_table" in names
    assert "strip_cover_artifacts" in names


def test_structured_stages_do_not_include_t10():
    """strip_web_fragments stays text-lane-only (trafilatura-specific)."""
    assert "strip_web_fragments" not in _stage_names(structured.STAGES)
    assert "strip_web_fragments" in _stage_names(text.STAGES)


def test_structured_stages_include_orphan_punctuation():
    """v1.0.3: lone | and > rows from Docling tables are stripped."""
    assert "strip_orphan_punctuation" in _stage_names(structured.STAGES)


def test_orphan_pipe_row_stripped_in_structured_lane():
    body = "# Title\n\nIntro.\n\n|\n\n## Section\n\nBody.\n"
    out, _ = run(body, "structured", PipelineOptions())
    assert "\n|\n" not in out


def test_t1_t6_stay_text_lane_only():
    """The line-wrap repair, dehyphenation, and other text-only stages
    must NOT run on Docling output (they damage tables)."""
    sn = _stage_names(structured.STAGES)
    for text_only_stage in (
        "repair_line_wraps",
        "dehyphenate",
        "dedupe_paragraphs",
        "dedupe_toc_block",
        "strip_running_headers_footers",
        "restore_lists_and_code",
    ):
        assert text_only_stage not in sn


def test_repeated_byline_stripped_in_structured_lane():
    body = (
        "# Title\n\nAbstract here.\n\n"
        "Author's Contact Information: Jane Doe et al.\n\n"
        "## Section 1\n\nBody.\n"
    )
    out, _ = run(body, "structured", PipelineOptions())
    assert "Author's Contact Information" not in out


def test_toc_table_stripped_in_structured_lane():
    body = (
        "# Title\n\nAbstract.\n\n"
        "| Section | Page |\n"
        "|---|---|\n"
        "| Introduction | 1 |\n"
        "| Methods | 5 |\n"
        "| Results | 12 |\n"
        "| Discussion | 24 |\n"
        "| Conclusion | 30 |\n\n"
        "## Introduction\n\nBody.\n\n## Methods\n\nm.\n\n## Results\n\nr.\n\n## Discussion\n\nd.\n\n## Conclusion\n\nc.\n"
    )
    out, _ = run(body, "structured", PipelineOptions())
    # The leading TOC table whose rows mirror later H2s should be stripped
    pre_h2 = out.split("\n## ", 1)[0]
    assert "| Introduction |" not in pre_h2
