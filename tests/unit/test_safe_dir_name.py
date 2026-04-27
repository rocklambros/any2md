"""Tests for safe_dir_name (F11: PDF image dir hardening)."""

from __future__ import annotations

import pytest

from any2md.utils import safe_dir_name


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("normal-doc_v2", "normal-doc_v2"),
        ("..", "untitled"),
        ("...", "untitled"),
        ("a/b/c", "a_b_c"),
        ("hello world", "hello_world"),
        ("", "untitled"),
        ("___", "untitled"),
        ("file.with.dots", "file_with_dots"),
        ("emoji \U0001f4a9 here", "emoji_here"),
    ],
)
def test_safe_dir_name(raw, expected):
    assert safe_dir_name(raw) == expected
