"""Tests for T5 — strip_running_headers_footers."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.text import strip_running_headers_footers


_PAGED_DOC = """\
ACME Quarterly Report\f
Page 1 of 3
Lorem ipsum body content here.
ACME Quarterly Report\f
Page 2 of 3
Dolor sit amet body.
ACME Quarterly Report\f
Page 3 of 3
End of body.
"""


def test_strips_repeated_header():
    out = strip_running_headers_footers(_PAGED_DOC, PipelineOptions())
    assert out.count("ACME Quarterly Report") <= 1


def test_strips_page_n_of_n_footer():
    out = strip_running_headers_footers(_PAGED_DOC, PipelineOptions())
    # "Page X of Y" lines should be reduced
    assert "Page 1 of 3" not in out


def test_no_form_feed_is_noop():
    """Without page boundary markers, this stage should not run."""
    text = "ACME Header\n\nBody1.\n\nACME Header\n\nBody2.\n"
    # No \f → no page boundaries → don't strip
    out = strip_running_headers_footers(text, PipelineOptions())
    assert out == text
