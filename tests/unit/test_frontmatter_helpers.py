"""Tests for SourceMeta and frontmatter module skeleton."""

import dataclasses

from any2md.frontmatter import SourceMeta


def test_source_meta_has_required_fields():
    fields = {f.name for f in dataclasses.fields(SourceMeta)}
    expected = {
        "title_hint", "authors", "organization", "date",
        "keywords", "pages", "word_count", "source_file",
        "source_url", "extracted_via", "lane",
    }
    assert expected <= fields, f"missing fields: {expected - fields}"


def test_source_meta_defaults_are_safe():
    meta = SourceMeta(
        title_hint=None, authors=[], organization=None, date=None,
        keywords=[], pages=None, word_count=None,
        source_file="x.txt", source_url=None,
        doc_type="txt", extracted_via="heuristic", lane="text",
    )
    assert meta.lane == "text"
    assert meta.extracted_via == "heuristic"
    assert meta.doc_type == "txt"
