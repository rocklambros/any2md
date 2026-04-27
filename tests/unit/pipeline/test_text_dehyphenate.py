"""Tests for T2 — dehyphenate."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.text import dehyphenate


def test_dehyphenates_when_joined_word_appears_elsewhere():
    text = "This shows co-\noperation between teams. Successful cooperation matters.\n"
    out = dehyphenate(text, PipelineOptions())
    assert "cooperation between teams" in out


def test_preserves_genuine_compound():
    text = "We use co-pilot integration.\nThe co-pilot is reliable.\n"
    # 'copilot' (joined) does NOT appear elsewhere → keep the hyphen.
    out = dehyphenate(text, PipelineOptions())
    assert "co-pilot integration" in out


def test_does_not_dehyphenate_across_paragraphs():
    text = "co-\n\noperation"
    # Blank line between → not a wrap, don't merge.
    out = dehyphenate(text, PipelineOptions())
    assert out == text


def test_no_hyphens_is_noop():
    text = "Plain text without any hyphenation.\n"
    assert dehyphenate(text, PipelineOptions()) == text
