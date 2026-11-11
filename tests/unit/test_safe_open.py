"""open_scanned binds a scanned file to a no-follow open (CWE-367, CWE-59).

The directory scan skips links, but the converter reads later. These
tests swap a scanned file, or a parent directory, for a link to a secret
outside the scan root after the scan, then call ``open_scanned`` and
check the secret is never read.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

import any2md._docling_cache as cache_mod
import any2md._safe_open as so
import any2md.converters as conv_mod
import any2md.converters.docx as docx_mod
import any2md.converters.html as html_mod
import any2md.converters.pdf as pdf_mod
import any2md.converters.txt as txt_mod
from any2md.pipeline import PipelineOptions

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="symlink creation needs privileges on Windows"
)

SECRET = "SECRET-SENTINEL-VALUE"
CAP = 10 * 1024 * 1024


@pytest.fixture
def tree(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "id_rsa").write_text(f"{SECRET}\n")
    (outside / "doc.txt").write_text(f"{SECRET}\n")
    root = tmp_path / "corpus"
    (root / "sub").mkdir(parents=True)
    (root / "top.txt").write_text("Top document body.\n")
    (root / "sub" / "doc.txt").write_text("Nested document body.\n")
    return root, outside


def test_reads_regular_file(tree):
    root, _ = tree
    src = so.open_scanned(root, Path("sub/doc.txt"), CAP)
    assert src.name == "doc.txt"
    assert src.path is None
    assert src.read_text() == "Nested document body.\n"
    assert src.mtime() == (root / "sub" / "doc.txt").stat().st_mtime


@posix_only
def test_file_swapped_for_symlink_is_skipped(tree):
    root, outside = tree
    (root / "top.txt").unlink()
    os.symlink(outside / "id_rsa", root / "top.txt")

    with pytest.raises(so.SkipSource) as exc:
        so.open_scanned(root, Path("top.txt"), CAP)
    assert exc.value.prefix == "SKIP (symlink)"


@posix_only
def test_parent_dir_swapped_for_symlink_is_skipped(tree):
    root, outside = tree
    shutil.rmtree(root / "sub")
    os.symlink(outside, root / "sub", target_is_directory=True)

    with pytest.raises(so.SkipSource) as exc:
        so.open_scanned(root, Path("sub/doc.txt"), CAP)
    assert exc.value.prefix == "SKIP (symlink)"


def test_parent_dir_swapped_for_file_is_skipped(tree):
    root, _ = tree
    shutil.rmtree(root / "sub")
    (root / "sub").write_text("not a directory\n")

    # The no-follow walk reports ENOTDIR as a skip. The Windows fallback
    # opens by path and fails with a plain OSError.
    expected = so.SkipSource if so._supports_nofollow_walk() else OSError
    with pytest.raises(expected):
        so.open_scanned(root, Path("sub/doc.txt"), CAP)


@posix_only
@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs os.mkfifo")
def test_fifo_is_rejected_without_blocking(tree):
    root, _ = tree
    (root / "top.txt").unlink()
    os.mkfifo(root / "top.txt")

    with pytest.raises(so.SkipSource) as exc:
        so.open_scanned(root, Path("top.txt"), CAP)
    assert exc.value.prefix == "SKIP (not a regular file)"


def test_file_over_cap_is_skipped(tree):
    root, _ = tree
    (root / "big.txt").write_bytes(b"x" * 2048)

    with pytest.raises(so.SkipSource) as exc:
        so.open_scanned(root, Path("big.txt"), 1024)
    assert exc.value.prefix == "SKIP (too large)"
    assert "2048 bytes, max 1024" in exc.value.detail


def test_file_grown_past_cap_after_fstat_is_skipped(tree, monkeypatch):
    root, _ = tree
    (root / "grow.txt").write_bytes(b"x" * 2048)
    real_fstat = os.fstat

    def small_fstat(fd):
        st = real_fstat(fd)
        # Report the size the file had before it grew.
        fields = list(st)
        fields[6] = 10
        return os.stat_result(fields)

    monkeypatch.setattr(so.os, "fstat", small_fstat)
    with pytest.raises(so.SkipSource) as exc:
        so.open_scanned(root, Path("grow.txt"), 1024)
    assert exc.value.prefix == "SKIP (too large)"


def test_missing_file_raises_oserror(tree):
    root, _ = tree
    with pytest.raises(FileNotFoundError):
        so.open_scanned(root, Path("gone.txt"), CAP)


@pytest.mark.parametrize("bad", ["../outside/id_rsa", "/etc/passwd", ""])
def test_rejects_paths_that_leave_the_root(tree, bad):
    root, _ = tree
    with pytest.raises(ValueError):
        so.open_scanned(root, Path(bad), CAP)


def test_text_matches_path_read_for_crlf_and_latin1(tree):
    root, _ = tree
    (root / "crlf.txt").write_bytes(b"one\r\ntwo\rthree\n")
    (root / "latin.txt").write_bytes("caf\xe9\n".encode("latin-1"))
    for name in ("crlf.txt", "latin.txt"):
        opened = so.open_scanned(root, Path(name), CAP).read_text()
        assert opened == so.as_source(root / name).read_text()


@posix_only
def test_fallback_without_dir_fd_rejects_symlink(tree, monkeypatch):
    root, outside = tree
    monkeypatch.setattr(so, "_supports_nofollow_walk", lambda: False)
    (root / "top.txt").unlink()
    os.symlink(outside / "id_rsa", root / "top.txt")

    with pytest.raises(so.SkipSource) as exc:
        so.open_scanned(root, Path("top.txt"), CAP)
    assert exc.value.prefix == "SKIP (symlink)"


def test_fallback_without_dir_fd_reads_regular_file(tree, monkeypatch):
    root, _ = tree
    monkeypatch.setattr(so, "_supports_nofollow_walk", lambda: False)
    src = so.open_scanned(root, Path("sub/doc.txt"), CAP)
    assert src.read_text() == "Nested document body.\n"


def test_fallback_rejects_file_swapped_after_open(tree, monkeypatch):
    root, outside = tree
    monkeypatch.setattr(so, "_supports_nofollow_walk", lambda: False)
    real_lstat = os.lstat

    def lstat_of_other_file(path):
        # The descriptor names one file, the path now names another.
        return real_lstat(outside / "id_rsa")

    monkeypatch.setattr(so.os, "lstat", lstat_of_other_file)
    with pytest.raises(so.SkipSource):
        so.open_scanned(root, Path("top.txt"), CAP)


def test_source_file_needs_exactly_one_backing():
    with pytest.raises(ValueError):
        so.SourceFile("a.txt")
    with pytest.raises(ValueError):
        so.SourceFile("a.txt", path=Path("a.txt"), data=b"x")


# Converters accept an opened source as well as a Path.


def _opened(fixture_dir: Path, name: str, as_name: str | None = None) -> so.SourceFile:
    """Build a bytes-backed source the way open_scanned does."""
    data = (fixture_dir / name).read_bytes()
    return so.SourceFile(as_name or name, data=data, mtime=0.0)


def test_convert_txt_from_opened_source(tmp_path):
    src = so.SourceFile("notes.txt", data=b"Plain body text here.\n", mtime=0.0)
    assert txt_mod.convert_txt(src, tmp_path, options=PipelineOptions())
    out = (tmp_path / "notes.md").read_text()
    assert "Plain body text here." in out
    assert 'source_file: "notes.txt"' in out


def test_convert_html_from_opened_source(fixture_dir, tmp_path):
    src = _opened(fixture_dir, "web_page.html")
    assert html_mod.convert_html(src, tmp_path, options=PipelineOptions())
    out = (tmp_path / "web_page.md").read_text()
    assert 'source_file: "web_page.html"' in out


def test_convert_pdf_from_opened_source(fixture_dir, tmp_path):
    src = _opened(fixture_dir, "multi_column.pdf")
    opts = PipelineOptions(backend="pymupdf4llm")
    assert pdf_mod.convert_pdf(src, tmp_path, options=opts)
    out = (tmp_path / "multi_column.md").read_text()
    assert 'source_file: "multi_column.pdf"' in out
    assert "pages: 2" in out


def test_convert_docx_from_opened_source(fixture_dir, tmp_path):
    src = _opened(fixture_dir, "table_heavy.docx")
    opts = PipelineOptions(backend="mammoth")
    assert docx_mod.convert_docx(src, tmp_path, options=opts)
    from_bytes = (tmp_path / "table_heavy.md").read_text()
    assert 'source_file: "table_heavy.docx"' in from_bytes

    path_out = tmp_path / "from_path"
    assert docx_mod.convert_docx(
        fixture_dir / "table_heavy.docx", path_out, options=opts
    )
    # Same document body and metadata whichever way the bytes arrive.
    assert (path_out / "table_heavy.md").read_text().split("\n---\n", 1)[1] == (
        from_bytes.split("\n---\n", 1)[1]
    )


def test_convert_file_dispatches_opened_source(tmp_path):
    src = so.SourceFile("dispatch.txt", data=b"Dispatched body.\n", mtime=0.0)
    assert conv_mod.convert_file(src, tmp_path, options=PipelineOptions())
    assert (tmp_path / "dispatch.md").exists()


class _RecordingConverter:
    def __init__(self) -> None:
        self.sources: list = []

    def convert(self, source):
        self.sources.append(source)

        class _Result:
            class document:  # noqa: N801  mimics Docling's attribute shape
                pictures: list = []

                @staticmethod
                def export_to_markdown() -> str:
                    return "# Title\n\nBody.\n"

        return _Result()


def test_docling_receives_document_stream_for_opened_source(monkeypatch):
    pytest.importorskip("docling")
    from docling.datamodel.base_models import DocumentStream

    conv = _RecordingConverter()
    monkeypatch.setattr(cache_mod, "get_docx_converter", lambda: conv)
    src = so.SourceFile("http:attacker.example#.docx", data=b"PK bytes", mtime=0.0)

    docx_mod._extract_via_docling(src)

    assert isinstance(conv.sources[0], DocumentStream)
    assert conv.sources[0].stream.read() == b"PK bytes"
