"""Tests for S2 — compact_tables."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.structured import compact_tables


def test_compact_pads_in_data_rows():
    table = (
        "| Col A    | Col B   |\n"
        "|----------|---------|\n"
        "| value 1  | value 2 |\n"
        "| value 3  | value 4 |\n"
    )
    out = compact_tables(table, PipelineOptions())
    assert "| value 1 | value 2 |" in out  # single space around values
    assert "value 1  " not in out  # no double-space padding


def test_compact_preserves_alignment_row():
    table = "| A | B |\n|:--|--:|\n| 1 | 2 |\n"
    out = compact_tables(table, PipelineOptions())
    assert "|:--|--:|" in out  # alignment row intact


def test_no_table_is_noop():
    text = "No tables here.\nJust prose.\n"
    assert compact_tables(text, PipelineOptions()) == text


def test_does_not_corrupt_inline_pipes_in_code():
    text = "`foo | bar` is shell pipe syntax\n"
    assert compact_tables(text, PipelineOptions()) == text
