"""open_scanned binds a scanned file to a no-follow open (CWE-367, CWE-59).

The directory scan skips links, but the converter reads later. These
tests swap a scanned file, or a parent directory, for a link to a secret
outside the scan root after the scan, then call ``open_scanned`` and
check the secret is never read.
"""

from __future__ import annotations

import errno
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


def _open_fds() -> int:
    return len(os.listdir("/dev/fd"))


def test_reads_regular_file(tree):
    root, _ = tree
    with so.open_scanned(root, Path("sub/doc.txt"), CAP) as src:
        assert src.name == "doc.txt"
        assert src.path is None
        assert src.data is None
        assert not src.closed
        assert src.read_text() == "Nested document body.\n"
        assert src.mtime() == (root / "sub" / "doc.txt").stat().st_mtime
        assert src.size() == len("Nested document body.\n")
    assert src.closed


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


def _report_small_size(monkeypatch):
    real_fstat = os.fstat

    def small_fstat(fd):
        st = real_fstat(fd)
        # Report the size the file had before it grew.
        fields = list(st)
        fields[6] = 10
        return os.stat_result(fields)

    monkeypatch.setattr(so.os, "fstat", small_fstat)


def test_full_read_of_file_grown_past_cap_fails(tree, monkeypatch):
    root, _ = tree
    (root / "grow.txt").write_bytes(b"x" * 2048)
    _report_small_size(monkeypatch)

    with so.open_scanned(root, Path("grow.txt"), 1024) as src:
        with pytest.raises(ValueError, match="grew past 1024 bytes"):
            src.read_text()
        with pytest.raises(ValueError, match="grew past 1024 bytes"):
            src.read_bytes()


def test_stream_read_of_file_grown_past_cap_fails(tree, monkeypatch):
    root, _ = tree
    (root / "grow.txt").write_bytes(b"x" * 2048)
    _report_small_size(monkeypatch)

    with so.open_scanned(root, Path("grow.txt"), 1024) as src:
        with src.open_binary() as fh, pytest.raises(ValueError, match="grew past"):
            fh.read()
        # A reader that seeks past the cap and reads there fails too.
        with src.open_binary() as fh, pytest.raises(ValueError, match="grew past"):
            fh.seek(1500)
            fh.read(10)


def test_stream_reads_up_to_the_cap(tree):
    root, _ = tree
    (root / "exact.txt").write_bytes(b"y" * 1024)
    with so.open_scanned(root, Path("exact.txt"), 1024) as src:
        with src.open_binary() as fh:
            assert fh.read() == b"y" * 1024
            fh.seek(0, os.SEEK_END)
            assert fh.tell() == 1024


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
        with so.open_scanned(root, Path(name), CAP) as src:
            assert src.read_text() == so.as_source(root / name).read_text()


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
    with so.open_scanned(root, Path("sub/doc.txt"), CAP) as src:
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


@posix_only
def test_hard_linked_file_is_skipped(tree):
    root, outside = tree
    os.link(outside / "id_rsa", root / "notes.txt")
    before = _open_fds()

    with pytest.raises(so.SkipSource) as exc:
        so.open_scanned(root, Path("notes.txt"), CAP)
    assert exc.value.prefix == "SKIP (hard link)"
    assert "notes.txt" in exc.value.detail
    assert "command line" in exc.value.detail
    assert _open_fds() == before


@posix_only
def test_hard_link_check_runs_in_the_fallback_too(tree, monkeypatch):
    root, outside = tree
    monkeypatch.setattr(so, "_supports_nofollow_walk", lambda: False)
    os.link(outside / "id_rsa", root / "notes.txt")

    with pytest.raises(so.SkipSource) as exc:
        so.open_scanned(root, Path("notes.txt"), CAP)
    assert exc.value.prefix == "SKIP (hard link)"


@posix_only
def test_swap_after_open_cannot_redirect_the_read(tree):
    root, outside = tree
    with so.open_scanned(root, Path("top.txt"), CAP) as src:
        (root / "top.txt").unlink()
        os.symlink(outside / "id_rsa", root / "top.txt")
        assert src.read_text() == "Top document body.\n"
        with src.open_binary() as fh:
            assert fh.read() == b"Top document body.\n"


def test_each_stream_starts_at_zero_and_keeps_its_own_position(tree):
    root, _ = tree
    with so.open_scanned(root, Path("top.txt"), CAP) as src:
        with src.open_binary() as first, src.open_binary() as second:
            assert first.read(4) == b"Top "
            assert second.read(3) == b"Top"
            assert first.read(8) == b"document"
        # Closing a stream leaves the source open for the next reader.
        assert not src.closed
        assert src.read_bytes() == b"Top document body.\n"


@posix_only
def test_close_is_idempotent_and_blocks_later_reads(tree):
    root, _ = tree
    before = _open_fds()
    with so.open_scanned(root, Path("top.txt"), CAP) as src:
        assert _open_fds() == before + 1
    # The with block closed it once. A second close must be a no-op.
    src.close()
    assert _open_fds() == before
    with pytest.raises(ValueError, match="closed"):
        src.read_bytes()
    with pytest.raises(ValueError, match="closed"):
        src.open_binary()


@posix_only
def test_skip_after_open_closes_the_descriptor(tree):
    root, _ = tree
    (root / "big.txt").write_bytes(b"x" * 2048)
    before = _open_fds()
    with pytest.raises(so.SkipSource):
        so.open_scanned(root, Path("big.txt"), 1024)
    assert _open_fds() == before


def test_short_file_reads_as_not_a_zip_through_a_descriptor(tree):
    from any2md._ooxml_guard import ArchiveRejected, check_ooxml_archive

    root, _ = tree
    (root / "tiny.docx").write_bytes(b"PK")
    with so.open_scanned(root, Path("tiny.docx"), CAP) as src:
        with pytest.raises(ArchiveRejected, match="not a valid OOXML"):
            check_ooxml_archive(src)


def test_path_backed_source_is_unchanged(tree):
    root, _ = tree
    src = so.as_source(root / "top.txt")
    assert src.path == root / "top.txt"
    assert src.read_bytes() == b"Top document body.\n"
    with src.open_binary() as fh:
        assert fh.read() == b"Top document body.\n"
    # Closing a path-backed source is allowed and changes nothing.
    src.close()
    assert src.read_text() == "Top document body.\n"


def test_source_file_needs_exactly_one_backing():
    with pytest.raises(ValueError):
        so.SourceFile("a.txt")
    with pytest.raises(ValueError):
        so.SourceFile("a.txt", path=Path("a.txt"), data=b"x")


# Converters accept an opened source as well as a Path.


def _opened(fixture_dir: Path, name: str) -> so.SourceFile:
    """Open a fixture the way the CLI opens a scanned file."""
    return so.open_scanned(fixture_dir, Path(name), CAP)


def test_convert_txt_from_opened_source(tmp_path):
    src = so.SourceFile("notes.txt", data=b"Plain body text here.\n", mtime=0.0)
    assert txt_mod.convert_txt(src, tmp_path, options=PipelineOptions())
    out = (tmp_path / "notes.md").read_text()
    assert "Plain body text here." in out
    assert 'source_file: "notes.txt"' in out


def test_convert_html_from_opened_source(fixture_dir, tmp_path):
    with _opened(fixture_dir, "web_page.html") as src:
        assert html_mod.convert_html(src, tmp_path, options=PipelineOptions())
    out = (tmp_path / "web_page.md").read_text()
    assert 'source_file: "web_page.html"' in out


def test_convert_pdf_from_opened_source(fixture_dir, tmp_path):
    opts = PipelineOptions(backend="pymupdf4llm")
    with _opened(fixture_dir, "multi_column.pdf") as src:
        assert pdf_mod.convert_pdf(src, tmp_path, options=opts)
    out = (tmp_path / "multi_column.md").read_text()
    assert 'source_file: "multi_column.pdf"' in out
    assert "pages: 2" in out


def test_convert_docx_from_opened_source(fixture_dir, tmp_path):
    opts = PipelineOptions(backend="mammoth")
    with _opened(fixture_dir, "table_heavy.docx") as src:
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


def test_docling_receives_document_stream_for_descriptor_source(
    fixture_dir, monkeypatch
):
    pytest.importorskip("docling")
    from docling.datamodel.base_models import DocumentStream

    conv = _RecordingConverter()
    monkeypatch.setattr(cache_mod, "get_docx_converter", lambda: conv)
    with _opened(fixture_dir, "table_heavy.docx") as src:
        docx_mod._extract_via_docling(src)

    expected = (fixture_dir / "table_heavy.docx").read_bytes()
    assert isinstance(conv.sources[0], DocumentStream)
    assert conv.sources[0].stream.read() == expected


class _CountingOpen:
    """Wrap pymupdf.open and count how many documents get parsed."""

    def __init__(self) -> None:
        self.calls = 0
        self._real = pdf_mod.pymupdf.open

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self._real(*args, **kwargs)


@pytest.mark.parametrize("from_descriptor", [True, False])
def test_pdf_is_parsed_once_per_conversion(
    fixture_dir, tmp_path, monkeypatch, from_descriptor
):
    counter = _CountingOpen()
    monkeypatch.setattr(pdf_mod.pymupdf, "open", counter)
    # No Docling and no backend override: the complexity check, the
    # metadata read, and the pymupdf4llm body all run.
    monkeypatch.setattr(pdf_mod, "has_docling", lambda: False)
    if from_descriptor:
        with _opened(fixture_dir, "multi_column.pdf") as src:
            assert pdf_mod.convert_pdf(src, tmp_path, options=PipelineOptions())
    else:
        path = fixture_dir / "multi_column.pdf"
        assert pdf_mod.convert_pdf(path, tmp_path, options=PipelineOptions())
    assert counter.calls == 1


def test_pdf_docling_fallback_reuses_the_document(fixture_dir, tmp_path, monkeypatch):
    counter = _CountingOpen()
    monkeypatch.setattr(pdf_mod.pymupdf, "open", counter)
    monkeypatch.setattr(pdf_mod, "has_docling", lambda: True)
    seen = []

    def failing_docling(src, options, output_dir, data=None):
        seen.append(data)
        raise RuntimeError("docling broke")

    monkeypatch.setattr(pdf_mod, "_extract_via_docling", failing_docling)
    with _opened(fixture_dir, "multi_column.pdf") as src:
        assert pdf_mod.convert_pdf(src, tmp_path, options=PipelineOptions())
    assert counter.calls == 1
    # Docling got the same bytes the document was parsed from.
    assert seen == [(fixture_dir / "multi_column.pdf").read_bytes()]
    assert 'extracted_via: "pymupdf4llm"' in (tmp_path / "multi_column.md").read_text()


def _limit_pread(monkeypatch, limit: int) -> list[int]:
    """Make pread reject counts above ``limit`` with EINVAL, as macOS does
    above INT_MAX, and record every count asked for."""
    real = os.pread
    sizes: list[int] = []

    def limited(fd, size, offset):
        sizes.append(size)
        if size > limit:
            raise OSError(errno.EINVAL, "Invalid argument")
        return real(fd, size, offset)

    monkeypatch.setattr(so.os, "pread", limited)
    monkeypatch.setattr(so, "_MAX_READ", limit)
    return sizes


@pytest.mark.skipif(not hasattr(os, "pread"), reason="needs os.pread")
def test_full_read_of_large_file_uses_bounded_preads(tree, monkeypatch):
    root, _ = tree
    payload = bytes(range(256)) * 64  # 16 KiB
    (root / "big.bin").write_bytes(payload)
    sizes = _limit_pread(monkeypatch, 4096)

    with so.open_scanned(root, Path("big.bin"), CAP) as src:
        assert src.read_bytes() == payload
    assert sizes and max(sizes) <= 4096


@pytest.mark.skipif(not hasattr(os, "pread"), reason="needs os.pread")
def test_stream_read_of_large_file_uses_bounded_preads(tree, monkeypatch):
    root, _ = tree
    payload = b"z" * 16384
    (root / "big.bin").write_bytes(payload)
    sizes = _limit_pread(monkeypatch, 4096)

    with so.open_scanned(root, Path("big.bin"), CAP) as src:
        with src.open_binary() as fh:
            assert fh.read(1 << 20) == payload
            fh.seek(0)
            assert fh.read() == payload
    assert sizes and max(sizes) <= 4096


@pytest.mark.skipif(not hasattr(os, "pread"), reason="needs os.pread")
def test_bounded_preads_still_enforce_the_cap(tree, monkeypatch):
    root, _ = tree
    (root / "grow.txt").write_bytes(b"x" * 20000)
    _report_small_size(monkeypatch)
    _limit_pread(monkeypatch, 4096)

    with so.open_scanned(root, Path("grow.txt"), 10000) as src:
        with pytest.raises(ValueError, match="grew past 10000 bytes"):
            src.read_bytes()


def test_max_read_stays_below_int_max():
    assert so._MAX_READ < 2**31 - 1
