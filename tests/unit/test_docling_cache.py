"""Unit tests for any2md/_docling_cache.py.

All tests in this file mock the Docling build callback. The real
Docling library is NOT required — Docling integration tests live in
tests/integration/test_docling_persistence.py and are gated by
pytest.mark.skipif(not has_docling()).
"""
from __future__ import annotations

import json

import pytest

from any2md._docling_cache import _canonicalize


def test_canonicalize_passes_through_scalars():
    assert _canonicalize(None) is None
    assert _canonicalize(42) == 42
    assert _canonicalize(3.14) == 3.14
    assert _canonicalize("hello") == "hello"
    assert _canonicalize(True) is True
    assert _canonicalize(False) is False


def test_canonicalize_sorts_dict_keys():
    out = _canonicalize({"b": 1, "a": 2, "c": 3})
    assert list(out.keys()) == ["a", "b", "c"]


def test_canonicalize_sorts_lists_of_scalars():
    # Same elements in different orders must canonicalize identically.
    a = _canonicalize(["b", "a", "c"])
    b = _canonicalize(["c", "b", "a"])
    assert a == b
    assert json.dumps(a) == json.dumps(b)


def test_canonicalize_sorts_nested_lists_in_dicts():
    a = _canonicalize({"k": ["b", "a"]})
    b = _canonicalize({"k": ["a", "b"]})
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_canonicalize_handles_heterogeneous_lists():
    # Mix of dicts, strings, numbers — must produce a deterministic
    # ordering via the JSON-string sort key.
    a = _canonicalize([{"x": 1}, "hello", 42])
    b = _canonicalize([42, {"x": 1}, "hello"])
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_canonicalize_recurses_into_nested_lists_of_dicts():
    a = _canonicalize([{"b": 2}, {"a": 1}])
    b = _canonicalize([{"a": 1}, {"b": 2}])
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
