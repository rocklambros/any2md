"""Untrusted names and error text must not reach the terminal raw.

Covers scan findings F7, F8, F9, F11 (CWE-117 / CWE-150). An attacker
who controls a filename, URL, or exception message must not be able to
emit ANSI/OSC sequences, C1 controls, bidi overrides, or extra lines on
stdout or stderr. Each test feeds a hostile token through one status
line and asserts the captured output is free of control characters
and keeps its expected line count.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import any2md.converters.docx as docx_mod
import any2md.converters.html as html_mod
import any2md.converters.pdf as pdf_mod
from any2md.converters.txt import convert_txt
from any2md.pipeline import PipelineOptions

# OSC 52 clipboard write, CSI erase-line, carriage return, single-byte
# C1 CSI, bidi override, and a newline that would forge a status line.
_HOSTILE = "evil\x1b]52;c;SGVsbG8=\x07\x1b[2K\r\x9b31m\u202e\nOK: forged"

# Everything a terminal could act on, except the newline that ends a line.
_UNSAFE_RE = re.compile(
    r"[\x00-\x09\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069\u200b-\u200f\ufeff]"
)


def _assert_clean(text: str, expected_lines: int) -> None:
    bad = _UNSAFE_RE.findall(text)
    assert not bad, f"unsafe chars reached the terminal: {bad!r} in {text!r}"
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == expected_lines, f"forged or missing lines: {text!r}"


def _hostile_copy(src: Path, dest_dir: Path, suffix: str) -> Path:
    dest = dest_dir / f"{_HOSTILE}{suffix}"
    shutil.copyfile(src, dest)
    return dest


def _raise_hostile(*_a, **_kw):
    raise RuntimeError(f"boom {_HOSTILE}")


# ---------------------------------------------------------------- PDF (F8)


def test_pdf_docling_fallback_warn_is_sanitized(
    fixture_dir, tmp_path, tmp_output_dir, monkeypatch, capsys
):
    src = _hostile_copy(fixture_dir / "multi_column.pdf", tmp_path, ".pdf")
    monkeypatch.setattr(pdf_mod, "has_docling", lambda: True)
    monkeypatch.setattr(pdf_mod, "_extract_via_docling", _raise_hostile)

    assert pdf_mod.convert_pdf(src, tmp_output_dir, options=PipelineOptions())
    captured = capsys.readouterr()
    assert "WARN: Docling extraction failed for evil" in captured.err
    assert "falling back to pymupdf4llm." in captured.err
    _assert_clean(captured.err, expected_lines=1)
    _assert_clean(captured.out, expected_lines=1)


def test_pdf_mammoth_backend_fail_is_sanitized(
    fixture_dir, tmp_path, tmp_output_dir, capsys
):
    src = _hostile_copy(fixture_dir / "multi_column.pdf", tmp_path, ".pdf")

    assert not pdf_mod.convert_pdf(
        src, tmp_output_dir, options=PipelineOptions(backend="mammoth")
    )
    err = capsys.readouterr().err
    assert "FAIL: evil" in err
    assert "backend 'mammoth' is not valid for PDF input" in err
    _assert_clean(err, expected_lines=1)


def test_pdf_skip_exists_is_sanitized(fixture_dir, tmp_path, tmp_output_dir, capsys):
    src = _hostile_copy(fixture_dir / "multi_column.pdf", tmp_path, ".pdf")
    (tmp_output_dir / pdf_mod.sanitize_filename(src.name)).write_text("x")

    assert pdf_mod.convert_pdf(src, tmp_output_dir)
    out = capsys.readouterr().out
    assert "SKIP (exists): evil" in out
    _assert_clean(out, expected_lines=1)


# --------------------------------------------------------------- DOCX (F9)


def test_docx_docling_fallback_warn_is_sanitized(
    fixture_dir, tmp_path, tmp_output_dir, monkeypatch, capsys
):
    src = _hostile_copy(fixture_dir / "table_heavy.docx", tmp_path, ".docx")
    monkeypatch.setattr(docx_mod, "has_docling", lambda: True)
    monkeypatch.setattr(docx_mod, "_extract_via_docling", _raise_hostile)

    assert docx_mod.convert_docx(src, tmp_output_dir, options=PipelineOptions())
    captured = capsys.readouterr()
    assert "WARN: Docling extraction failed for evil" in captured.err
    assert "falling back to mammoth." in captured.err
    _assert_clean(captured.err, expected_lines=1)
    _assert_clean(captured.out, expected_lines=1)


def test_docx_pymupdf4llm_backend_fail_is_sanitized(
    fixture_dir, tmp_path, tmp_output_dir, capsys
):
    src = _hostile_copy(fixture_dir / "table_heavy.docx", tmp_path, ".docx")

    assert not docx_mod.convert_docx(
        src, tmp_output_dir, options=PipelineOptions(backend="pymupdf4llm")
    )
    err = capsys.readouterr().err
    assert "FAIL: evil" in err
    assert "backend 'pymupdf4llm' is not valid for DOCX input" in err
    _assert_clean(err, expected_lines=1)


# ------------------------------------------------------- DOCX FALLBACK (F11)


def test_docx_fallback_line_is_sanitized(
    fixture_dir, tmp_path, tmp_output_dir, monkeypatch, capsys
):
    src = _hostile_copy(fixture_dir / "table_heavy.docx", tmp_path, ".docx")
    monkeypatch.setattr(docx_mod, "has_docling", lambda: True)
    monkeypatch.setattr(
        docx_mod,
        "_extract_via_docling",
        lambda _p: ("# Title\n\nBody.\n", "docling", ["dropped list item"]),
    )

    assert docx_mod.convert_docx(
        src, tmp_output_dir, options=PipelineOptions(docx_fallback_on_warn=True)
    )
    err = capsys.readouterr().err
    assert "FALLBACK: evil" in err
    assert "msword_backend warning(s); re-running via mammoth" in err
    _assert_clean(err, expected_lines=1)


# ------------------------------------------------------------ HTML and TXT


def test_html_too_large_fail_is_sanitized(
    fixture_dir, tmp_path, tmp_output_dir, monkeypatch, capsys
):
    src = _hostile_copy(fixture_dir / "web_page.html", tmp_path, ".html")
    monkeypatch.setattr(html_mod, "_MAX_FILE_SIZE", 1)

    assert not html_mod.convert_html(src, tmp_output_dir)
    err = capsys.readouterr().err
    assert "FAIL: evil" in err
    assert "file too large" in err
    _assert_clean(err, expected_lines=1)


def test_txt_ok_line_is_sanitized(tmp_path, tmp_output_dir, capsys):
    src = tmp_path / f"{_HOSTILE}.txt"
    src.write_text("Hello world.\n\nSecond paragraph.\n", encoding="utf-8")

    assert convert_txt(src, tmp_output_dir)
    out = capsys.readouterr().out
    assert "OK: evil" in out
    _assert_clean(out, expected_lines=1)


def test_ordinary_names_print_unchanged(fixture_dir, tmp_output_dir, capsys):
    assert html_mod.convert_html(fixture_dir / "web_page.html", tmp_output_dir)
    out = capsys.readouterr().out
    assert out.startswith("  OK: web_page.md (")


# -------------------------------------------------------------- CLI (F7)


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "any2md", *args],
        capture_output=True,
        text=True,
    )


def test_cli_skip_too_large_is_sanitized(fixture_dir, tmp_path):
    src = _hostile_copy(fixture_dir / "web_page.html", tmp_path, ".html")
    r = _run("-o", str(tmp_path / "out"), "--max-file-size", "1", str(src))
    assert "SKIP (too large): evil" in r.stderr
    _assert_clean(r.stderr, expected_lines=1)
    _assert_clean(r.stdout, expected_lines=2)


def test_cli_skip_exists_is_sanitized(fixture_dir, tmp_path):
    src = _hostile_copy(fixture_dir / "web_page.html", tmp_path, ".html")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / pdf_mod.sanitize_filename(src.name)).write_text("x")

    r = _run("-o", str(out_dir), str(src))
    assert "SKIP (exists): evil" in r.stdout
    _assert_clean(r.stdout, expected_lines=3)


@pytest.mark.parametrize("name", ["report.pdf", "My Notes v2.docx", "café.txt"])
def test_safe_oneline_keeps_ordinary_names(name):
    from any2md._logging import safe_oneline

    assert safe_oneline(name) == name
