"""Test Docling image save refuses to follow symlinks."""

from __future__ import annotations

import os
import sys

import pytest

# Skip on Windows where O_NOFOLLOW doesn't exist
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="O_NOFOLLOW POSIX-only")


def test_image_save_refuses_symlink_target(tmp_path, capsys):
    """If images_dir/foo.png is a symlink to /tmp/sentinel, the converter
    must refuse to write through it."""
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("ORIGINAL")
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    symlink = images_dir / "foo.png"
    os.symlink(sentinel, symlink)

    from PIL import Image
    from any2md.converters.pdf import _save_image_safely

    img = Image.new("RGB", (4, 4), (255, 0, 0))
    _save_image_safely(symlink, img)

    # Symlink target must remain unchanged
    assert sentinel.read_text() == "ORIGINAL"


def test_image_save_normal_path_works(tmp_path):
    from PIL import Image
    from any2md.converters.pdf import _save_image_safely

    img = Image.new("RGB", (4, 4), (0, 255, 0))
    target = tmp_path / "ok.png"
    _save_image_safely(target, img)
    assert target.exists()
    assert target.stat().st_size > 0


def test_image_save_existing_file_skips_silently(tmp_path):
    from PIL import Image
    from any2md.converters.pdf import _save_image_safely

    target = tmp_path / "existing.png"
    target.write_bytes(b"prior")
    img = Image.new("RGB", (4, 4), (0, 0, 255))
    _save_image_safely(target, img)
    # File contents preserved (skip on EEXIST)
    assert target.read_bytes() == b"prior"
