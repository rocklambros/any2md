"""Tests for the lane-agnostic strip_orphan_punctuation stage (v1.0.3).

Extracted from T10 strip_web_fragments so Docling output (structured
lane) can also drop lone | and > rows that survive Docling's table
parser. The trafilatura-specific short-fragment removal stays inside
strip_web_fragments and only runs on the text lane.
"""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.text import strip_orphan_punctuation


def test_drops_lone_pipe_lines_aggressive():
    text = (
        "Real paragraph one.\n"
        "\n"
        "|\n"
        "\n"
        "Real paragraph two.\n"
    )
    out = strip_orphan_punctuation(text, PipelineOptions(profile="aggressive"))
    assert "|\n" not in out
    assert "Real paragraph one." in out
    assert "Real paragraph two." in out


def test_drops_lone_gt_lines_aggressive():
    text = "para a\n\n>\n\npara b\n"
    out = strip_orphan_punctuation(text, PipelineOptions(profile="aggressive"))
    lines = [ln.strip() for ln in out.split("\n")]
    assert ">" not in lines
    assert "para a" in out and "para b" in out


def test_preserves_lines_with_other_content():
    # `|` and `>` only stripped when they are the entire line content.
    text = "para |\n\n> quoted text\n"
    out = strip_orphan_punctuation(text, PipelineOptions(profile="aggressive"))
    assert "para |" in out
    assert "> quoted text" in out


def test_conservative_profile_is_noop():
    text = "para\n\n|\n\npara\n"
    out = strip_orphan_punctuation(text, PipelineOptions(profile="conservative"))
    assert out == text
