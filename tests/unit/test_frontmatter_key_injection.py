"""Test frontmatter override-key validator (regex; reject control chars)."""

from __future__ import annotations

import pytest

from any2md.frontmatter import _validate_keys, compose, SourceMeta
from any2md.pipeline import PipelineOptions


def test_accepts_valid_keys():
    _validate_keys({"title": "x", "doc-id": "y", "_internal": "z", "Authors": []})
    # no exception


def test_rejects_newline_injection_top_level():
    with pytest.raises(ValueError, match="invalid frontmatter key"):
        _validate_keys({"innocent\nmalicious_key": "evil"})


def test_rejects_colon_in_key():
    with pytest.raises(ValueError, match="invalid frontmatter key"):
        _validate_keys({"a:b": "x"})


def test_rejects_space_in_key():
    with pytest.raises(ValueError, match="invalid frontmatter key"):
        _validate_keys({"a b": "x"})


def test_rejects_digit_first():
    with pytest.raises(ValueError, match="invalid frontmatter key"):
        _validate_keys({"1leading": "x"})


def test_rejects_nested_invalid_key():
    with pytest.raises(ValueError, match="invalid frontmatter key.*sub.*bad"):
        _validate_keys({"meta": {"sub\nbad": "x"}})


def test_compose_rejects_injection_via_overrides():
    meta = SourceMeta(
        title_hint="t", authors=[], organization=None, date="2026-01-01",
        keywords=[], pages=None, word_count=0, source_file=None, source_url=None,
        doc_type="text", extracted_via="test", lane="text",
    )
    options = PipelineOptions()
    overrides = {"innocent\nmalicious_key": "evil"}
    with pytest.raises(ValueError, match="invalid frontmatter key"):
        compose("body", meta, options, overrides=overrides)
