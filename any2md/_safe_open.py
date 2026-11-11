"""Bind files found by a directory scan to no-follow opens.

``cli._scan_directory`` skips symlinks, but the scan and the converter's
read happen at different times. Anyone who can write to the scanned tree
can swap a scanned file, or one of its parent directories, for a link to
``~/.ssh/id_rsa`` between the two, and the converter would copy the
target into the output (CWE-367, CWE-59). ``open_scanned`` closes that
window: it walks from a descriptor of the scan root and opens every
path component with ``O_NOFOLLOW``, checks the final descriptor with
``fstat``, and keeps that descriptor open for the converter. Every read
goes through the descriptor, so a swap after the open cannot redirect
it.

A hard link is a second name for the same file, which ``O_NOFOLLOW``
cannot detect. On a file system without protected hard links (macOS,
or Linux with ``fs.protected_hardlinks=0``) anyone who can write to the
tree can link a file they cannot read, such as ``~victim/.netrc``, into
it. ``open_scanned`` therefore skips a scanned file with more than one
link (CWE-62).

A file named on the command line keeps the old behavior and follows
links, because the user chose it. ``SourceFile.from_path`` covers that
case and library callers that pass a ``Path``.
"""

from __future__ import annotations

import errno
import io
import os
import stat
from pathlib import Path
from typing import BinaryIO

from any2md.utils import decode_text_with_fallback, read_text_with_fallback

_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
# Windows opens descriptors in text mode unless told otherwise, which
# would rewrite CRLF pairs inside binary PDF and DOCX data.
_O_BINARY = getattr(os, "O_BINARY", 0)
# A FIFO swapped in for a scanned file would block a plain O_RDONLY open
# until a writer shows up. O_NONBLOCK makes the open return at once so
# the fstat check can reject it.
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)

# Linux reports ELOOP for an O_NOFOLLOW open of a link. macOS reports
# ELOOP for a file link and ENOTDIR for a link opened with O_DIRECTORY.
# FreeBSD reports EMLINK.
_LINK_ERRNOS = {errno.ELOOP, errno.EMLINK, errno.ENOTDIR}

_CHUNK = 1024 * 1024


def _supports_nofollow_walk() -> bool:
    return bool(_O_NOFOLLOW and _O_DIRECTORY and os.open in os.supports_dir_fd)


class SkipSource(Exception):
    """A scanned file the CLI must skip, not fail.

    ``prefix`` is the status label (for example ``SKIP (symlink)``) and
    ``detail`` the text after it. The CLI prints both through
    ``_logging.warn``, which strips control characters from the name.
    """

    def __init__(self, prefix: str, detail: str) -> None:
        super().__init__(detail)
        self.prefix = prefix
        self.detail = detail


def _pread(fd: int, size: int, offset: int) -> bytes:
    """Read at ``offset`` without depending on the descriptor's position.

    Several streams can read one descriptor in turn (the OOXML guard,
    then mammoth), and each keeps its own position. ``os.pread`` leaves
    the shared offset alone. Windows has no ``pread``, so there every
    read seeks first, which gives the same result in one thread.
    """
    if hasattr(os, "pread"):
        return os.pread(fd, size, offset)
    os.lseek(fd, offset, os.SEEK_SET)
    return os.read(fd, size)


def _grew_error(max_size: int) -> ValueError:
    # ValueError, because every converter reports it as a per-file FAIL.
    return ValueError(f"file grew past {max_size} bytes after it was opened")


def _read_capped(fd: int, max_size: int, size_hint: int) -> bytes:
    """Read the whole file from ``fd``, refusing more than ``max_size``.

    The first read asks for one byte past the size ``fstat`` reported,
    so a file read in one call needs no join and no second copy. Any
    later read asks for at most one byte past the cap, so a file that
    grew after the check fails instead of being truncated or read
    without bound.
    """
    chunks: list[bytes] = []
    total = 0
    want = min(size_hint, max_size) + 1
    while True:
        chunk = _pread(fd, want, total)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_size:
            raise _grew_error(max_size)
        want = min(_CHUNK, max_size + 1 - total)
    if len(chunks) == 1:
        return chunks[0]
    return b"".join(chunks)


class _DescriptorReader(io.RawIOBase):
    """A seekable read-only stream over a descriptor the source owns.

    Closing the stream leaves the descriptor open, so each reader can
    close its own stream and the next one still works. Reads never
    return bytes past ``max_size``: a read that would cross the cap
    raises, which keeps the size limit on the descriptor even when the
    file grows after the ``fstat`` check.
    """

    def __init__(self, fd: int, max_size: int) -> None:
        super().__init__()
        self._fd = fd
        self._max_size = max_size
        self._pos = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        self._checkClosed()
        return self._pos

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        self._checkClosed()
        if whence == os.SEEK_SET:
            new = offset
        elif whence == os.SEEK_CUR:
            new = self._pos + offset
        elif whence == os.SEEK_END:
            new = os.fstat(self._fd).st_size + offset
        else:
            raise ValueError(f"invalid whence ({whence})")
        if new < 0:
            # OSError, as a real file raises. zipfile seeks before the
            # end to find the central directory and treats OSError from
            # a short file as "not a zip".
            raise OSError(errno.EINVAL, f"negative seek position {new}")
        self._pos = new
        return new

    def readinto(self, buffer) -> int:
        self._checkClosed()
        view = memoryview(buffer).cast("B")
        if not len(view):
            return 0
        # Ask for at most one byte past the cap. Getting that byte means
        # the file grew past the limit after it was checked.
        room = self._max_size + 1 - self._pos
        data = _pread(self._fd, max(1, min(len(view), room)), self._pos)
        if data and self._pos + len(data) > self._max_size:
            raise _grew_error(self._max_size)
        view[: len(data)] = data
        self._pos += len(data)
        return len(data)


class SourceFile:
    """One document to convert, backed by a path, a descriptor, or bytes.

    A path-backed source hands the path to each parsing library, as
    any2md always has. A descriptor-backed source comes from
    ``open_scanned``: every read goes through the descriptor it checked,
    never through the name, so no later swap can change what the
    converter reads. A bytes-backed source holds data already in memory.
    ``name`` is the original file name in every case, so ``source_file``
    and output names stay the same.

    A descriptor-backed source holds an open file until ``close``. Use
    it as a context manager. Closing a path or bytes source does nothing.
    """

    __slots__ = ("name", "path", "data", "_mtime", "_fh", "_size", "_max_size")

    def __init__(
        self,
        name: str,
        *,
        path: Path | None = None,
        data: bytes | None = None,
        mtime: float | None = None,
    ) -> None:
        if (path is None) == (data is None):
            raise ValueError("SourceFile needs exactly one of path or data")
        self.name = name
        self.path = path
        self.data = data
        self._mtime = mtime
        self._fh: BinaryIO | None = None
        self._size = 0
        self._max_size = 0

    @classmethod
    def from_path(cls, path: Path) -> SourceFile:
        path = Path(path)
        return cls(path.name, path=path)

    @classmethod
    def _from_descriptor(
        cls, name: str, fh: BinaryIO, st: os.stat_result, max_size: int
    ) -> SourceFile:
        src = cls.__new__(cls)
        src.name = name
        src.path = None
        src.data = None
        src._mtime = st.st_mtime
        src._fh = fh
        src._size = st.st_size
        src._max_size = max_size
        return src

    @property
    def stem(self) -> str:
        return Path(self.name).stem

    @property
    def suffix(self) -> str:
        return Path(self.name).suffix

    @property
    def closed(self) -> bool:
        return self._fh is not None and self._fh.closed

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()

    def __enter__(self) -> SourceFile:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _fd(self) -> int:
        assert self._fh is not None
        if self._fh.closed:
            raise ValueError(f"I/O operation on closed source file {self.name!r}")
        return self._fh.fileno()

    def mtime(self) -> float:
        if self.path is not None:
            return self.path.stat().st_mtime
        return self._mtime if self._mtime is not None else 0.0

    def size(self) -> int:
        if self.path is not None:
            return self.path.stat().st_size
        if self.data is not None:
            return len(self.data)
        return self._size

    def open_binary(self) -> BinaryIO:
        """Return a fresh binary stream. Each call starts at offset 0.

        Closing the stream does not close a descriptor-backed source.
        """
        if self.path is not None:
            return open(self.path, "rb")
        if self.data is not None:
            return io.BytesIO(self.data)
        return io.BufferedReader(_DescriptorReader(self._fd(), self._max_size))

    def read_bytes(self) -> bytes:
        """Return the whole file. A descriptor read stops at the size cap."""
        if self.path is not None:
            return self.path.read_bytes()
        if self.data is not None:
            return self.data
        return _read_capped(self._fd(), self._max_size, self._size)

    def read_text(self) -> str:
        if self.path is not None:
            return read_text_with_fallback(self.path)
        return decode_text_with_fallback(self.read_bytes())

    def docling_input(self, data: bytes | None = None):
        """Return what ``DocumentConverter.convert`` should receive.

        Docling resolves a str source as a URL first, so a file named
        ``http:host#.pdf`` would be fetched. A Path is read from disk and
        a ``DocumentStream`` never reaches URL resolution at all.

        ``DocumentStream`` accepts only an ``io.BytesIO`` (Docling checks
        the type), so a descriptor-backed source is read into memory
        here. A caller that already holds the bytes passes them as
        ``data`` to skip a second read.
        """
        if self.path is not None:
            return Path(self.path)
        from docling.datamodel.base_models import DocumentStream

        if data is None:
            data = self.read_bytes()
        return DocumentStream(name=self.name, stream=io.BytesIO(data))


def as_source(src: Path | SourceFile) -> SourceFile:
    """Accept the ``Path`` library callers pass, or an opened source."""
    if isinstance(src, SourceFile):
        return src
    return SourceFile.from_path(Path(src))


def _check_regular(st: os.stat_result, label: str, max_size: int) -> None:
    if not stat.S_ISREG(st.st_mode):
        raise SkipSource("SKIP (not a regular file)", label)
    if st.st_nlink > 1:
        raise SkipSource(
            "SKIP (hard link)",
            f"{label} (one of {st.st_nlink} hard links to the same file. "
            f"Name it on the command line to convert it if you trust it.)",
        )
    if st.st_size > max_size:
        raise SkipSource(
            "SKIP (too large)", f"{label} ({st.st_size} bytes, max {max_size})"
        )


def _open_nofollow(root: Path, parts: tuple[str, ...], label: str) -> int:
    """Open ``root/parts`` with no component below ``root`` followed."""
    # The root itself is followed: the user named it, and a link there
    # is the user's choice, not something planted in the tree.
    cur = os.open(root, os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC)
    try:
        for part in parts[:-1]:
            try:
                nxt = os.open(
                    part,
                    os.O_RDONLY | _O_NOFOLLOW | _O_DIRECTORY | _O_CLOEXEC,
                    dir_fd=cur,
                )
            except OSError as e:
                if e.errno in _LINK_ERRNOS:
                    raise SkipSource(
                        "SKIP (symlink)",
                        f"{label} (a parent directory is a link or changed after the scan)",
                    ) from None
                raise
            os.close(cur)
            cur = nxt
        try:
            return os.open(
                parts[-1],
                os.O_RDONLY | _O_NOFOLLOW | _O_NONBLOCK | _O_CLOEXEC,
                dir_fd=cur,
            )
        except OSError as e:
            if e.errno in (errno.ELOOP, errno.EMLINK):
                raise SkipSource("SKIP (symlink)", label) from None
            raise
    finally:
        os.close(cur)


def _open_checked_fallback(path: Path, label: str) -> int:
    """Open ``path`` where ``O_NOFOLLOW`` with ``dir_fd`` is unavailable.

    Windows has neither. The open follows links, so the check runs after
    it: the descriptor must name the same file that ``lstat`` sees at
    the path, and that path must not be a link. Residual risk: a parent
    directory swapped for a link or junction and swapped back between
    the open and the ``lstat`` passes this check, and junctions are not
    reported by ``lstat`` as links on every Python release. Creating
    links on Windows needs privileges or Developer Mode, which narrows
    who can mount the attack.
    """
    fd = os.open(path, os.O_RDONLY | _O_BINARY | _O_NONBLOCK | _O_CLOEXEC)
    try:
        lst = os.lstat(path)
        if stat.S_ISLNK(lst.st_mode) or not os.path.samestat(os.fstat(fd), lst):
            raise SkipSource("SKIP (symlink)", label)
    except BaseException:
        os.close(fd)
        raise
    return fd


def open_scanned(root: Path, relative: Path, max_size: int) -> SourceFile:
    """Open a file found by a directory scan of ``root`` without following links.

    ``relative`` is the path below ``root`` the scan reported. Returns a
    descriptor-backed ``SourceFile`` that the caller must close. Reads
    through it never return more than ``max_size`` bytes. Raises
    ``SkipSource`` for a link, a hard link, a non-regular file, or a
    file over the cap, and ``OSError`` for anything else (for example a
    file removed after the scan).
    """
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or ".." in parts:
        raise ValueError(f"not a path below the scan root: {relative}")
    label = str(Path(root) / relative)

    if _supports_nofollow_walk():
        fd = _open_nofollow(Path(root), parts, label)
    else:
        fd = _open_checked_fallback(Path(root) / relative, label)
    try:
        st = os.fstat(fd)
        _check_regular(st, label, max_size)
        # Regular files ignore O_NONBLOCK, so clearing it changes no
        # read. It keeps the descriptor in the mode readers expect.
        if _O_NONBLOCK:
            os.set_blocking(fd, True)
        # Unbuffered: every read goes through _pread at an explicit
        # offset, so a buffer here would hold bytes no reader uses.
        fh = os.fdopen(fd, "rb", buffering=0)
    except BaseException:
        os.close(fd)
        raise
    return SourceFile._from_descriptor(parts[-1], fh, st, max_size)
