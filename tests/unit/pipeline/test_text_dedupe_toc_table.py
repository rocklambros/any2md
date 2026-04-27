"""Tests for T7 — dedupe_toc_table."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.text import dedupe_toc_table


_DOC_WITH_TOC_TABLE = """\
# Document Title

| # | Section | Page |
|---|---------|------|
| 1 | Introduction | 1 |
| 2 | Methods | 5 |
| 3 | Results | 12 |
| 4 | Discussion | 24 |
| 5 | Conclusion | 30 |

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


def test_strips_toc_table_when_aggressive_profile():
    out = dedupe_toc_table(_DOC_WITH_TOC_TABLE, PipelineOptions(profile="aggressive"))
    # Table content gone
    assert "| 1 | Introduction | 1 |" not in out
    assert "|---|---------|------|" not in out
    # Headings still present
    assert "## Introduction" in out
    assert "## Conclusion" in out


def test_conservative_keeps_toc_table():
    out = dedupe_toc_table(_DOC_WITH_TOC_TABLE, PipelineOptions(profile="conservative"))
    assert "| 1 | Introduction | 1 |" in out


def test_table_not_in_first_30_percent_is_kept():
    # Build doc where the table sits past the 30% mark.
    body_filler = "\n".join(["Some long paragraph line of text."] * 60)
    doc = (
        "# Title\n\n"
        + body_filler
        + "\n\n"
        + "| # | Section | Page |\n"
        + "|---|---------|------|\n"
        + "| 1 | Foo | 1 |\n"
        + "| 2 | Bar | 2 |\n"
        + "| 3 | Baz | 3 |\n"
        + "| 4 | Qux | 4 |\n"
        + "\n"
        + "## Foo\n\n"
        + "## Bar\n\n"
        + "## Baz\n\n"
        + "## Qux\n"
    )
    out = dedupe_toc_table(doc, PipelineOptions(profile="aggressive"))
    # Late-occurring table should NOT be stripped (only leading TOC tables)
    assert "| 1 | Foo | 1 |" in out


def test_table_with_low_heading_overlap_is_kept():
    # Less than 70% of TOC entries match later headings → keep the table.
    doc = """\
# Title

| # | Section | Page |
|---|---------|------|
| 1 | Apples | 1 |
| 2 | Bananas | 2 |
| 3 | Cherries | 3 |
| 4 | Dates | 4 |

## Different Heading

Body content here.

## Another Heading

More body.
"""
    out = dedupe_toc_table(doc, PipelineOptions(profile="aggressive"))
    assert "| 1 | Apples | 1 |" in out


def test_no_table_is_noop():
    text = "# Title\n\n## Section\n\nBody content.\n"
    out = dedupe_toc_table(text, PipelineOptions(profile="aggressive"))
    assert out == text


def test_strips_toc_table_with_leader_dot_padding():
    """Docling renders TOC entries as 'Title.................Page' — the
    leader-dot run must be stripped before matching against body headings.

    Regression for issue #17 item 1.
    """
    doc = """\
# Document Title

| # | Section | Page |
|---|---------|------|
| 1 | 1.1. Purpose............................................................................. | 1 |
| 2 | 1.2. Scope................................................................................ | 2 |
| 3 | 2.1. Backup Frequency................................................................. | 5 |
| 4 | 2.2. Retention.......................................................................... | 8 |

## 1.1. Purpose

Body of purpose.

## 1.2. Scope

Body of scope.

## 2.1. Backup Frequency

Body of backup frequency.

## 2.2. Retention

End body.
"""
    out = dedupe_toc_table(doc, PipelineOptions(profile="aggressive"))
    # Table content gone (the leader-dot padded entries should not survive)
    assert "Purpose..............." not in out
    assert "|---|---------|------|" not in out
    # Headings still present
    assert "## 1.1. Purpose" in out
    assert "## 2.2. Retention" in out
