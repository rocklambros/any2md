"""Tests for T4 — dedupe_toc_block."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.text import dedupe_toc_block


_DOC_WITH_TOC = """\
1. Introduction ............ 1
2. Methods ................. 5
3. Results ................. 12
4. Discussion .............. 24
5. Conclusion .............. 30

# Document Title

## Introduction

Body of introduction.

## Methods

Body of methods.

## Results

Body of results.

## Discussion

Body of discussion.

## Conclusion

End body.
"""


def test_strips_toc_when_aggressive_profile():
    out = dedupe_toc_block(_DOC_WITH_TOC, PipelineOptions(profile="aggressive"))
    assert "1. Introduction" not in out.split("# Document Title")[0]
    # Headings still present
    assert "## Introduction" in out


def test_conservative_keeps_toc():
    out = dedupe_toc_block(_DOC_WITH_TOC, PipelineOptions(profile="conservative"))
    assert "1. Introduction" in out


def test_no_toc_block_is_noop():
    text = "# Title\n\n## Section\n\nBody.\n"
    out = dedupe_toc_block(text, PipelineOptions(profile="aggressive"))
    assert out == text


def test_does_not_strip_toc_without_matching_headings():
    text = """\
1. Aaa ........... 1
2. Bbb ........... 2
3. Ccc ........... 3
4. Ddd ........... 4
5. Eee ........... 5

# Real Document

## Different Heading

Body.
"""
    # TOC entries don't match headings → keep TOC
    out = dedupe_toc_block(text, PipelineOptions(profile="aggressive"))
    assert "1. Aaa" in out
