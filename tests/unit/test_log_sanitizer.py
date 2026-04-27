"""Tests for Docling-warning control-char sanitizer (F2)."""

from __future__ import annotations

from any2md.converters.docx import _sanitize_log_text


def test_strips_ansi_escape():
    s = "msg \x1b[31mRED\x1b[0m end"
    assert _sanitize_log_text(s) == "msg [31mRED[0m end"


def test_strips_null_byte():
    assert _sanitize_log_text("a\x00b") == "ab"


def test_preserves_printable_ascii():
    s = "Plain ASCII text: hello, world! 123."
    assert _sanitize_log_text(s) == s


def test_preserves_tab_and_newline():
    assert _sanitize_log_text("a\tb\nc") == "a\tb\nc"


def test_strips_c1_controls():
    assert _sanitize_log_text("a\x85b\x9fc") == "abc"
