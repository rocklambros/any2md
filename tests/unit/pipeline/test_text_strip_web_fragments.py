"""Tests for T10 — strip_web_fragments."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.text import strip_web_fragments


def test_drops_orphan_punctuation_lines():
    text = "Real paragraph one.\n\n|\n\n>\n\nReal paragraph two.\n"
    out = strip_web_fragments(text, PipelineOptions(profile="aggressive"))
    assert "Real paragraph one." in out
    assert "Real paragraph two." in out
    # Orphan single-character lines gone
    lines = [ln.strip() for ln in out.split("\n")]
    assert "|" not in lines
    assert ">" not in lines


def test_drops_short_incomplete_sentence_between_blanks():
    text = "Real paragraph here.\n\nfragment text\n\nAnother real paragraph follows.\n"
    out = strip_web_fragments(text, PipelineOptions(profile="aggressive"))
    assert "Real paragraph here." in out
    assert "Another real paragraph follows." in out
    assert "fragment text" not in out


def test_keeps_short_legitimate_heading_text():
    text = "Real paragraph here.\n\nContents\n\nAnother real paragraph.\n"
    out = strip_web_fragments(text, PipelineOptions(profile="aggressive"))
    assert "Contents" in out


def test_conservative_profile_is_noop():
    text = "Real paragraph.\n\n|\n\nfragment text\n\nAnother paragraph.\n"
    out = strip_web_fragments(text, PipelineOptions(profile="conservative"))
    assert out == text


def test_keeps_short_first_line():
    # No preceding paragraph, so the line cannot be a fragment trafilatura
    # cut from the end of one.
    text = "Title Line\n\nThe body paragraph.\n"
    out = strip_web_fragments(text, PipelineOptions(profile="aggressive"))
    assert out == text


def test_keeps_short_line_after_leading_blank_lines():
    text = "\n\nTitle Line\n\nThe body paragraph.\n"
    out = strip_web_fragments(text, PipelineOptions(profile="aggressive"))
    assert out == text


def test_keeps_short_line_after_heading():
    text = "# Report\n\nsection intro\n\nThe body paragraph.\n"
    out = strip_web_fragments(text, PipelineOptions(profile="aggressive"))
    assert out == text


def test_keeps_short_line_after_unterminated_paragraph():
    text = "A paragraph with no period\n\nshort line\n\nThe body paragraph.\n"
    out = strip_web_fragments(text, PipelineOptions(profile="aggressive"))
    assert out == text


def test_drops_consecutive_fragments_without_blank_run():
    # A dropped line must not become the "text before" the next one, and
    # each drop takes its trailing blank line with it.
    text = "A sentence.\n\nfrag one\n\nfrag two\n\nMore text here."
    out = strip_web_fragments(text, PipelineOptions(profile="aggressive"))
    assert out == "A sentence.\n\nMore text here."


def test_drop_leaves_one_blank_line():
    text = "Real paragraph here.\n\nfragment text\n\nAnother real paragraph follows.\n"
    out = strip_web_fragments(text, PipelineOptions(profile="aggressive"))
    assert out == "Real paragraph here.\n\nAnother real paragraph follows.\n"


def test_short_line_after_code_block_is_kept():
    # A closing fence is not the end of a sentence, and the stage does not
    # reach back past the block, so nothing marks the line as a fragment.
    text = "A sentence.\n\n```\ncode\n```\n\nshort line\n\nMore prose here."
    out = strip_web_fragments(text, PipelineOptions(profile="aggressive"))
    assert out == text


def test_fragment_after_sentence_after_code_block_is_dropped():
    text = "```\ncode.\n```\n\nA sentence.\n\nfrag text\n\nMore prose here."
    out = strip_web_fragments(text, PipelineOptions(profile="aggressive"))
    assert out == "```\ncode.\n```\n\nA sentence.\n\nMore prose here."


def test_kept_short_line_is_the_text_before():
    text = "No period here\n\nshort line\n\nfrag two\n\nThe body paragraph.\n"
    out = strip_web_fragments(text, PipelineOptions(profile="aggressive"))
    assert out == text
