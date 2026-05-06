"""Tests for the _logging module — sanitizer + warn/fail helpers."""

from __future__ import annotations

from any2md._logging import _sanitize_log_text, safe_oneline, warn, fail


def test_strips_ansi_escape():
    s = "msg \x1b[31mRED\x1b[0m end"
    assert _sanitize_log_text(s) == "msg [31mRED[0m end"


def test_strips_bidi_override():
    # U+202E RIGHT-TO-LEFT OVERRIDE inside an "evil" payload
    s = "report‮txt.fdp"
    assert _sanitize_log_text(s) == "reporttxt.fdp"


def test_strips_zero_width():
    # U+200B, U+200C, U+200D, U+FEFF
    s = "a​b‌c‍d﻿e"
    assert _sanitize_log_text(s) == "abcde"


def test_strips_bidi_isolates():
    # U+2066 LEFT-TO-RIGHT ISOLATE through U+2069 POP DIRECTIONAL ISOLATE
    s = "x⁦y⁧z⁨w⁩v"
    assert _sanitize_log_text(s) == "xyzwv"


def test_preserves_newlines_in_sanitize_log_text():
    s = "line1\nline2\rline3"
    assert _sanitize_log_text(s) == "line1\nline2\rline3"


def test_safe_oneline_strips_newlines():
    s = "a\nb\rc"
    assert safe_oneline(s) == "a b c"


def test_safe_oneline_strips_control_too():
    s = "a\x00b\x1bc\nd"
    assert safe_oneline(s) == "abc d"


def test_warn_writes_prefixed_to_stderr(capsys):
    warn("hi")
    captured = capsys.readouterr()
    assert captured.err == "  WARN: hi\n"
    assert captured.out == ""


def test_fail_writes_prefixed_to_stderr(capsys):
    fail("oops")
    captured = capsys.readouterr()
    assert captured.err == "  FAIL: oops\n"


def test_warn_sanitizes_input(capsys):
    warn("evil\x00‮payload")
    captured = capsys.readouterr()
    assert "\x00" not in captured.err
    assert "‮" not in captured.err
    assert captured.err == "  WARN: evilpayload\n"


def test_warn_custom_prefix(capsys):
    warn("note", prefix="INFO")
    assert capsys.readouterr().err == "  INFO: note\n"
