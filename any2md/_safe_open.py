"""Bind files found by a directory scan to no-follow opens.

``cli._scan_directory`` skips symlinks, but the scan and the converter's
read happen at different times. Anyone who can write to the scanned tree
can swap a scanned file, or one of its parent directories, for a link to
``~/.ssh/id_rsa`` between the two, and the converter would copy the
target into the output (CWE-367, CWE-59). ``open_scanned`` closes that
window: it walks from a descriptor of the scan root and opens every
path component with ``O_NOFOLLOW``, checks the final descriptor with
``fstat``, and reads the bytes from that descriptor. A swap after the
open cannot redirect a read that is already done.

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


class SourceFile:
    """One document to convert, backed by a path or by bytes already read.

    A path-backed source hands the path to each parsing library, as
    any2md always has. A bytes-backed source comes from
    ``open_scanned`` and never touches the filesystem again, so no later
    swap can change what the converter reads. ``name`` is the original
    file name in both cases, so ``source_file`` and output names stay
    the same.
    """

    __slots__ = ("name", "path", "data", "_mtime")

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

    @classmethod
    def from_path(cls, path: Path) -> SourceFile:
        path = Path(path)
        return cls(path.name, path=path)

    @property
    def stem(self) -> str:
        return Path(self.name).stem

    @property
    def suffix(self) -> str:
        return Path(self.name).suffix

    def mtime(self) -> float:
        if self.path is not None:
            return self.path.stat().st_mtime
        return self._mtime if self._mtime is not None else 0.0

    def size(self) -> int:
        if self.path is not None:
            return self.path.stat().st_size
        return len(self.data or b"")

    def open_binary(self) -> BinaryIO:
        """Return a fresh binary stream. Each call starts at offset 0."""
        if self.path is not None:
            return open(self.path, "rb")
        return io.BytesIO(self.data or b"")

    def read_text(self) -> str:
        if self.path is not None:
            return read_text_with_fallback(self.path)
        return decode_text_with_fallback(self.data or b"")

    def docling_input(self):
        """Return what ``DocumentConverter.convert`` should receive.

        Docling resolves a str source as a URL first, so a file named
        ``http:host#.pdf`` would be fetched. A Path is read from disk and
        a ``DocumentStream`` never reaches URL resolution at all.
        """
        if self.path is not None:
            return Path(self.path)
        from docling.datamodel.base_models import DocumentStream

        return DocumentStream(name=self.name, stream=io.BytesIO(self.data or b""))


def as_source(src: Path | SourceFile) -> SourceFile:
    """Accept the ``Path`` library callers pass, or an opened source."""
    if isinstance(src, SourceFile):
        return src
    return SourceFile.from_path(Path(src))


def _read_capped(fd: int, max_size: int, label: str) -> bytes:
    """Read the whole file from ``fd``, refusing more than ``max_size``.

    The read asks for one byte past the cap so a file that grew after
    the ``fstat`` check is caught instead of truncated.
    """
    chunks: list[bytes] = []
    remaining = max_size + 1
    while remaining > 0:
        chunk = os.read(fd, min(remaining, 1024 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    if len(data) > max_size:
        raise SkipSource(
            "SKIP (too large)", f"{label} (grew past {max_size} bytes while read)"
        )
    return data


def _check_regular(st: os.stat_result, label: str, max_size: int) -> None:
    if not stat.S_ISREG(st.st_mode):
        raise SkipSource("SKIP (not a regular file)", label)
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
    """Read a file found by a directory scan of ``root`` without following links.

    ``relative`` is the path below ``root`` the scan reported. Returns a
    bytes-backed ``SourceFile`` holding at most ``max_size`` bytes.
    Raises ``SkipSource`` for a link, a non-regular file, or a file over
    the cap, and ``OSError`` for anything else (for example a file
    removed after the scan).
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
        data = _read_capped(fd, max_size, label)
    finally:
        os.close(fd)
    return SourceFile(parts[-1], data=data, mtime=st.st_mtime)
