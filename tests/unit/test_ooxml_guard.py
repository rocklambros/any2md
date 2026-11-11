"""Zip-bomb guard for OOXML inputs (DOCX, PPTX, XLSX).

The guard runs before mammoth, Docling, or the docProps reader opens the
archive, and reads the same bytes or handle the converter will read.
"""

from __future__ import annotations

import zipfile

import pytest

import any2md._ooxml_guard as guard
import any2md.converters.docx as docx_mod
import any2md.converters.office as office
from any2md._safe_open import SourceFile
from any2md.pipeline import PipelineOptions
from tests._office_fixtures import build_pptx, build_xlsx


def _zip_bytes(tmp_path, members: dict[str, bytes]) -> bytes:
    path = tmp_path / "a.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path.read_bytes()


def test_real_office_files_pass(tmp_path, fixture_dir):
    guard.check_ooxml_archive(SourceFile.from_path(fixture_dir / "table_heavy.docx"))
    guard.check_ooxml_archive(
        SourceFile.from_path(build_pptx(tmp_path / "d.pptx", [("T", "B")]))
    )
    guard.check_ooxml_archive(
        SourceFile.from_path(build_xlsx(tmp_path / "b.xlsx", {"S": [["a"]]}))
    )


def test_bytes_backed_source_is_checked(tmp_path):
    data = _zip_bytes(tmp_path, {"word/document.xml": b"<x/>"})
    guard.check_ooxml_archive(SourceFile("a.docx", data=data))


def test_not_a_zip_is_rejected():
    with pytest.raises(guard.ArchiveRejected, match="not a valid OOXML"):
        guard.check_ooxml_archive(SourceFile("a.xlsx", data=b"plain text"))


def test_rejection_is_a_value_error():
    # Every converter reports ValueError as a per-file failure.
    assert issubclass(guard.ArchiveRejected, ValueError)


def test_total_uncompressed_size_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "MAX_TOTAL_UNCOMPRESSED", 1000)
    data = _zip_bytes(tmp_path, {"a.xml": b"x" * 600, "b.xml": b"y" * 600})
    with pytest.raises(guard.ArchiveRejected, match="total uncompressed size"):
        guard.check_ooxml_archive(SourceFile("a.docx", data=data))


def test_extreme_compression_ratio(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "RATIO_CHECK_MIN_SIZE", 1024)
    data = _zip_bytes(tmp_path, {"xl/worksheets/sheet1.xml": b"\0" * 2_000_000})
    with pytest.raises(guard.ArchiveRejected, match="compression ratio"):
        guard.check_ooxml_archive(SourceFile("a.xlsx", data=data))


def test_small_members_skip_ratio_check(tmp_path):
    # A tiny, highly repetitive part (styles, shared strings) is normal.
    data = _zip_bytes(tmp_path, {"xl/styles.xml": b"\0" * 100_000})
    guard.check_ooxml_archive(SourceFile("a.xlsx", data=data))


def test_member_count_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "MAX_MEMBERS", 3)
    data = _zip_bytes(tmp_path, {f"p{i}.xml": b"<x/>" for i in range(4)})
    with pytest.raises(guard.ArchiveRejected, match="members"):
        guard.check_ooxml_archive(SourceFile("a.pptx", data=data))


# ---- converters call the guard before any library reads the file -------


def _bomb(tmp_path, monkeypatch, name):
    monkeypatch.setattr(guard, "MAX_MEMBERS", 1)
    data = _zip_bytes(tmp_path, {"a.xml": b"<x/>", "b.xml": b"<x/>"})
    return SourceFile(name + "\x1b[31m\n", data=data)


@pytest.mark.parametrize("backend", [None, "mammoth", "docling"])
def test_docx_rejects_bomb_before_any_backend(tmp_path, monkeypatch, capsys, backend):
    def must_not_run(*a, **k):
        raise AssertionError("backend read a rejected archive")

    monkeypatch.setattr(docx_mod, "_extract_via_mammoth", must_not_run)
    monkeypatch.setattr(docx_mod, "_extract_via_docling", must_not_run)
    monkeypatch.setattr(docx_mod, "_read_docx_metadata", must_not_run)
    src = _bomb(tmp_path, monkeypatch, "bomb.docx")

    ok = docx_mod.convert_docx(
        src, tmp_path / "out", options=PipelineOptions(backend=backend), force=True
    )

    assert ok is False
    err = capsys.readouterr().err
    assert err.startswith("  FAIL: bomb.docx")
    assert "members" in err
    assert "\x1b" not in err and err.count("\n") == 1


@pytest.mark.parametrize("fmt", ["pptx", "xlsx"])
def test_office_rejects_bomb_before_docling(tmp_path, monkeypatch, capsys, fmt):
    def must_not_run(*a, **k):
        raise AssertionError("library read a rejected archive")

    monkeypatch.setattr(office, "has_docling", lambda: True)
    monkeypatch.setattr(office, "_convert_via_docling", must_not_run)
    monkeypatch.setattr(office, "_read_docx_metadata", must_not_run)
    src = _bomb(tmp_path, monkeypatch, f"bomb.{fmt}")

    assert office.convert_office(src, tmp_path / "out", fmt, force=True) is False
    err = capsys.readouterr().err
    assert err.startswith(f"  FAIL: bomb.{fmt}")
    assert "members" in err
    assert "Docling could not convert" not in err
    assert err.count("\n") == 1
