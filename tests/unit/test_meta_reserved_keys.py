"""Tests for filter_reserved_overrides (F5: --meta integrity)."""

from __future__ import annotations

import pytest

from any2md.frontmatter import _RESERVED_OVERRIDE_KEYS, filter_reserved_overrides


@pytest.mark.parametrize("key", sorted(_RESERVED_OVERRIDE_KEYS))
def test_each_reserved_key_dropped_with_warn(capsys, key):
    out = filter_reserved_overrides({key: "x", "title": "ok"})
    assert key not in out
    assert out["title"] == "ok"
    err = capsys.readouterr().err
    assert key in err and "reserved" in err.lower()


def test_non_reserved_keys_preserved(capsys):
    overrides = {"title": "T", "authors": ["a"], "organization": "o"}
    out = filter_reserved_overrides(overrides)
    assert out == overrides
    assert capsys.readouterr().err == ""


def test_nested_dict_under_non_reserved_untouched():
    overrides = {"generation_metadata": {"authored_by": "human"}}
    out = filter_reserved_overrides(overrides)
    assert out == overrides


def test_none_passes_through():
    assert filter_reserved_overrides(None) is None


def test_empty_dict_passes_through():
    assert filter_reserved_overrides({}) == {}
