"""Regression tests for v1.0.3 C8 double-encoded HTML entity handling.

v1.0.2 C8 ran ``html.unescape`` once, which decoded ``&amp;amp;`` → ``&amp;``
but left a surviving entity. Real-world Docling output on academic PDFs
contains double-encoded entities; v1.0.3 loops the unescape until stable.
"""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.cleanup import decode_html_entities


def test_double_encoded_amp_fully_decoded():
    text = "AI &amp;amp; SOCIETY 39, 3 (Oct. 2022).\n"
    out = decode_html_entities(text, PipelineOptions())
    assert "AI & SOCIETY" in out
    assert "&amp;" not in out
    assert "&amp;amp;" not in out


def test_triple_encoded_amp_decoded_within_max_iterations():
    # &amp;amp;amp; = & encoded 3 times; loop should fully decode.
    text = "X &amp;amp;amp; Y\n"
    out = decode_html_entities(text, PipelineOptions())
    assert "X & Y" in out


def test_single_encoded_still_works():
    """v1.0.2 single-encoded test still passes."""
    text = "AI &amp; ML\n"
    out = decode_html_entities(text, PipelineOptions())
    assert out.strip() == "AI & ML"


def test_loop_does_not_overrun_legitimate_amp():
    """A literal '&' should not be rewritten or affected."""
    text = "Cmd-line: foo & bar\n"
    out = decode_html_entities(text, PipelineOptions())
    assert out == text


def test_double_encoded_inside_fence_preserved():
    """Code blocks should NOT be unescaped at all."""
    text = "```\nliteral &amp;amp; here\n```\n"
    out = decode_html_entities(text, PipelineOptions())
    assert "&amp;amp;" in out  # untouched inside fence
