"""Write --save-images files for every converter: PDF, DOCX, PPTX, XLSX.

Each converter numbers its pictures in document order and hands them to
one ``ImageWriter``, which owns ``<output>/images/<stem>/``. The rules:

- Every file is written atomically: a temporary file created in the
  same folder with ``O_EXCL|O_NOFOLLOW`` (``tempfile.mkstemp``), then
  renamed onto ``imgN.<ext>``. A rename replaces a symlink at the target
  rather than writing through it, so no write ever follows a link.
- Images are staged first and published by ``commit`` only after the
  converter has written its final Markdown, which ``commit`` receives.
  ``discard`` drops them when the conversion or the write fails, so a
  failed lane (for example Docling before its mammoth fallback) leaves
  no files behind, and a failed write under ``--force`` leaves the old
  images its old Markdown links.
- The folder must stay inside the output directory. ``images`` or
  ``<stem>`` being a symlink, or the folder resolving anywhere else,
  stops all writes for the file with a warning.
- Without ``overwrite`` an existing ``imgN`` is kept, as before. The
  converter only gets here when its Markdown is new, and the file name
  is linked either way.
- With ``overwrite`` (``--force``) each ``imgN`` is replaced, and
  ``commit`` removes every ``imgN.*`` this run did not link, so a
  document that lost a picture neither links nor ships its old file.
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from any2md import _logging
from any2md.utils import sanitize_filename

# The names this writer owns. Anything else in the folder is left alone.
_IMAGE_NAME_RE = re.compile(r"^img\d+\.[A-Za-z0-9]+$")


def _reserve(target: Path) -> bool:
    """Claim ``target`` as a new, empty file. False when the name exists.

    ``O_CREAT|O_EXCL|O_NOFOLLOW`` claims the name without following a
    link and without hard links, which exFAT, FAT32, and some SMB or
    FUSE mounts refuse. The caller then renames the finished temporary
    file over the claimed name, so readers never see a partial image.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        os.close(os.open(target, flags, 0o600))
    except FileExistsError:
        return False
    return True


def image_folder_name(source_name: str) -> str:
    """The image folder for a source: its output ``.md`` name without ``.md``.

    ``sanitize_filename`` gives the output name, and #60 fails a run in
    which two inputs share one, so two documents never share a folder.
    A stricter rename (``safe_dir_name``) would merge names such as
    "Report v2" and "Report.v2", or any two all-CJK names. The name holds
    no path separator. "." and ".." become "_." and "_..", which no
    output name can produce, since ``sanitize_filename`` strips leading
    underscores.
    """
    stem = sanitize_filename(source_name).removesuffix(".md")
    if stem in ("", ".", ".."):
        return "_" + stem
    return stem


def _remove(path: str) -> None:
    # A file that is already gone is the state the caller wants.
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)


class ImageWriter:
    """Save one document's images under ``<output_dir>/images/<stem>/``."""

    def __init__(self, output_dir: Path, source_name: str, overwrite: bool) -> None:
        self._output_dir = output_dir
        self._name = image_folder_name(source_name)
        self._folder = output_dir / "images" / self._name
        self._overwrite = overwrite
        # Names linked from the body this run, and the temporary file
        # each staged image waits in until ``commit``.
        self._linked: set[str] = set()
        self._staged: dict[str, str] = {}
        self._ready: bool | None = None

    def link(self, file_name: str) -> str:
        """The body's relative link to ``file_name``, percent-encoded.

        The folder name may hold spaces, parentheses, or any script, which
        a Markdown link destination cannot carry as they are.
        """
        return f"images/{quote(self._name)}/{file_name}"

    def write_png(self, number: int, pil_image: Any) -> str | None:
        """Save a PIL image as ``imgN.png``. Returns its link, or None."""
        return self._write(
            f"img{number}.png", lambda fp: pil_image.save(fp, format="PNG")
        )

    def write_bytes(self, number: int, ext: str, data: bytes) -> str | None:
        """Save image bytes as they are, as ``imgN.<ext>``. Returns its link, or None."""
        return self._write(f"img{number}.{ext}", lambda fp: fp.write(data))

    def commit(self, markdown: str | None = None) -> None:
        """Publish the staged images, then under ``overwrite`` drop stale ones.

        The converter calls this once its Markdown is complete and passes
        it in. Only a staged image whose link appears in ``markdown`` is
        published, so nothing is saved that the body does not link (a
        picture Docling left out of the Markdown, for example). Without
        ``markdown`` every staged image is published. A staged image that
        cannot be published is reported, and its temporary file is removed.
        """
        staged, self._staged = self._staged, {}
        for file_name, tmp in staged.items():
            if markdown is not None and f"]({self.link(file_name)})" not in markdown:
                self._linked.discard(file_name)
                _remove(tmp)
                continue
            target = self._folder / file_name
            try:
                if not self._overwrite and not _reserve(target):
                    # A file took the name since staging. It is kept.
                    os.unlink(tmp)
                    continue
                os.replace(tmp, target)
            except OSError as e:
                _logging.warn(f"failed to save image {file_name}: {e}")
                _remove(tmp)
        if self._overwrite and self._folder_is_safe(create=False):
            self._remove_stale()

    def discard(self) -> None:
        """Drop the staged images. Called when the conversion fails."""
        staged, self._staged = self._staged, {}
        for tmp in staged.values():
            _remove(tmp)

    def _remove_stale(self) -> None:
        try:
            entries = list(os.scandir(self._folder))
        except OSError:
            return
        for entry in entries:
            if not _IMAGE_NAME_RE.match(entry.name) or entry.name in self._linked:
                continue
            if entry.is_dir(follow_symlinks=False):
                continue
            try:
                # unlink removes a symlink itself, never its target.
                os.unlink(entry.path)
            except OSError as e:
                _logging.warn(f"failed to remove stale image {entry.name}: {e}")

    def _write(self, file_name: str, emit: Callable[[Any], Any]) -> str | None:
        """Stage one image in a temporary file. Returns its link, or None."""
        if not self._folder_is_safe(create=True):
            return None
        target = self._folder / file_name
        if not self._overwrite and os.path.lexists(target):
            # Kept as it was. A symlink is never linked from the body.
            return None if os.path.islink(target) else self.link(file_name)
        fd, tmp = tempfile.mkstemp(prefix=".img-", suffix=".tmp", dir=self._folder)
        try:
            with os.fdopen(fd, "wb") as fp:
                emit(fp)
        except Exception as e:  # noqa: BLE001 -- one bad picture must not fail the file
            _logging.warn(f"failed to save image {file_name}: {e}")
            _remove(tmp)
            return None
        self._staged[file_name] = tmp
        self._linked.add(file_name)
        return self.link(file_name)

    def _folder_is_safe(self, create: bool) -> bool:
        """True when the image folder exists inside the output directory.

        Checked once per document. ``create`` makes the folder first.
        """
        if self._ready is not None:
            return self._ready
        images = self._output_dir / "images"
        if os.path.islink(images) or os.path.islink(self._folder):
            self._refuse()
            return False
        if not self._folder.is_dir():
            if not create:
                return False
            try:
                self._folder.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                _logging.warn(f"failed to create image folder: {e}")
                self._ready = False
                return False
        try:
            self._folder.resolve().relative_to(self._output_dir.resolve())
        except ValueError:
            self._refuse()
            return False
        if os.path.islink(images) or os.path.islink(self._folder):
            self._refuse()
            return False
        self._ready = True
        return True

    def _refuse(self) -> None:
        _logging.warn(
            f"refusing to write images for {self._name}: the image folder "
            "is a symlink or lies outside the output directory"
        )
        self._ready = False
