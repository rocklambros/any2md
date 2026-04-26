"""Tests for S4 — enforce_heading_hierarchy."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.structured import enforce_heading_hierarchy


def test_clean_doc_is_unchanged():
    text = "# Title\n\n## Sec\n\n### Sub\n"
    assert enforce_heading_hierarchy(text, PipelineOptions()) == text


def test_promotes_first_heading_when_no_h1():
    text = "## First Heading\n\n### Sub\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert out.startswith("# First Heading\n")


def test_demotes_subsequent_h1():
    text = "# A\n\nbody\n\n# B\n\nmore\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert out.count("# A") == 1
    assert "## B" in out


def test_repairs_skipped_levels():
    text = "# A\n\n#### Deep\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    # H1 → H4 became H1 → H2 (one level deeper than H1)
    assert "## Deep" in out


def test_no_headings_is_noop():
    text = "Plain body, no headings.\n"
    assert enforce_heading_hierarchy(text, PipelineOptions()) == text
