"""Write --save-images files for every converter: PDF, DOCX, PPTX, XLSX.

Each converter numbers its pictures in document order and hands them to
one ``ImageWriter``, which owns ``<output>/images/<stem>/``. The rules:

- Every file is written atomically: a temporary file created in the
  same folder with ``O_EXCL|O_NOFOLLOW`` (``tempfile.mkstemp``), then
  renamed onto ``imgN.<ext>``. A rename replaces a symlink at the target
  rather than writing through it, so no write ever follows a link.
- The folder must stay inside the output directory. ``images`` or
  ``<stem>`` being a symlink, or the folder resolving anywhere else,
  stops all writes for the file with a warning.
- Without ``overwrite`` an existing ``imgN`` is kept, as before. The
  converter only gets here when its Markdown is new, and the file name
  is linked either way.
- With ``overwrite`` (``--force``) each ``imgN`` is replaced, and
  ``finish`` removes every ``imgN.*`` this run did not write, so a
  document that lost a picture neither links nor ships its old file.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

from any2md import _logging
from any2md.utils import safe_dir_name

# The names this writer owns. Anything else in the folder is left alone.
_IMAGE_NAME_RE = re.compile(r"^img\d+\.[A-Za-z0-9]+$")


class ImageWriter:
    """Save one document's images under ``<output_dir>/images/<stem>/``."""

    def __init__(self, output_dir: Path, stem: str, overwrite: bool) -> None:
        self._output_dir = output_dir
        self._name = safe_dir_name(stem)
        self._folder = output_dir / "images" / self._name
        self._overwrite = overwrite
        self._written: set[str] = set()
        self._ready: bool | None = None

    def link(self, file_name: str) -> str:
        """The body's relative link to ``file_name``."""
        return f"images/{self._name}/{file_name}"

    def write_png(self, number: int, pil_image: Any) -> str | None:
        """Save a PIL image as ``imgN.png``. Returns its link, or None."""
        return self._write(
            f"img{number}.png", lambda fp: pil_image.save(fp, format="PNG")
        )

    def write_bytes(self, number: int, ext: str, data: bytes) -> str | None:
        """Save image bytes as they are, as ``imgN.<ext>``. Returns its link, or None."""
        return self._write(f"img{number}.{ext}", lambda fp: fp.write(data))

    def finish(self) -> None:
        """Under ``overwrite``, remove the ``imgN`` files this run did not write."""
        if not self._overwrite or not self._folder_is_safe(create=False):
            return
        try:
            entries = list(os.scandir(self._folder))
        except OSError:
            return
        for entry in entries:
            if not _IMAGE_NAME_RE.match(entry.name) or entry.name in self._written:
                continue
            if entry.is_dir(follow_symlinks=False):
                continue
            try:
                # unlink removes a symlink itself, never its target.
                os.unlink(entry.path)
            except OSError as e:
                _logging.warn(f"failed to remove stale image {entry.name}: {e}")

    def _write(self, file_name: str, emit: Callable[[Any], Any]) -> str | None:
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
            if self._overwrite:
                os.replace(tmp, target)
            else:
                try:
                    # link() refuses an existing name, so a file that
                    # appeared since the check above is kept.
                    os.link(tmp, target)
                except FileExistsError:
                    pass
                os.unlink(tmp)
        except Exception as e:  # noqa: BLE001 -- one bad picture must not fail the file
            _logging.warn(f"failed to save image {file_name}: {e}")
            if os.path.lexists(tmp):
                os.unlink(tmp)
            return None
        self._written.add(file_name)
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
