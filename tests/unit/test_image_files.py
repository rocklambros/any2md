"""The shared writer every converter uses for --save-images files."""

from __future__ import annotations

import os
import sys

import pytest

from any2md._image_files import ImageWriter

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="symlink and O_NOFOLLOW checks are POSIX-only"
)


class _Png:
    """Stands in for a PIL image: ``save`` writes the given bytes."""

    def __init__(self, data: bytes = b"PNGDATA"):
        self.data = data

    def save(self, fp, format):
        assert format == "PNG"
        fp.write(self.data)


def _writer(tmp_path, overwrite=False, stem="deck"):
    return ImageWriter(tmp_path / "out", stem, overwrite=overwrite)


def test_writes_png_and_bytes_and_returns_links(tmp_path):
    w = _writer(tmp_path)

    assert w.write_png(1, _Png(b"one")) == "images/deck/img1.png"
    assert w.write_bytes(2, "jpg", b"two") == "images/deck/img2.jpg"

    folder = tmp_path / "out" / "images" / "deck"
    assert (folder / "img1.png").read_bytes() == b"one"
    assert (folder / "img2.jpg").read_bytes() == b"two"
    # Atomic writes leave no temporary files behind.
    assert sorted(p.name for p in folder.iterdir()) == ["img1.png", "img2.jpg"]


def test_without_overwrite_an_existing_file_is_kept(tmp_path):
    folder = tmp_path / "out" / "images" / "deck"
    folder.mkdir(parents=True)
    (folder / "img1.png").write_bytes(b"prior")

    link = _writer(tmp_path).write_png(1, _Png(b"new"))

    assert link == "images/deck/img1.png"
    assert (folder / "img1.png").read_bytes() == b"prior"


def test_with_overwrite_an_existing_file_is_replaced(tmp_path):
    folder = tmp_path / "out" / "images" / "deck"
    folder.mkdir(parents=True)
    (folder / "img1.png").write_bytes(b"prior")

    _writer(tmp_path, overwrite=True).write_png(1, _Png(b"new"))

    assert (folder / "img1.png").read_bytes() == b"new"


@pytest.mark.parametrize("overwrite", [False, True])
def test_a_symlink_at_the_target_is_never_written_through(tmp_path, overwrite):
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("ORIGINAL")
    folder = tmp_path / "out" / "images" / "deck"
    folder.mkdir(parents=True)
    os.symlink(sentinel, folder / "img1.png")

    link = _writer(tmp_path, overwrite=overwrite).write_png(1, _Png(b"new"))

    assert sentinel.read_text() == "ORIGINAL"
    if overwrite:
        # The link itself is replaced by a regular file.
        assert not os.path.islink(folder / "img1.png")
        assert (folder / "img1.png").read_bytes() == b"new"
        assert link == "images/deck/img1.png"
    else:
        assert os.path.islink(folder / "img1.png")
        assert link is None


def test_finish_with_overwrite_removes_stale_images_only(tmp_path):
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("ORIGINAL")
    folder = tmp_path / "out" / "images" / "deck"
    folder.mkdir(parents=True)
    for name in ("img1.png", "img2.png", "img3.jpg", "notes.txt", "image1.png"):
        (folder / name).write_bytes(b"old")
    os.symlink(sentinel, folder / "img9.png")

    w = _writer(tmp_path, overwrite=True)
    w.write_png(1, _Png(b"new"))
    w.finish()

    assert sorted(p.name for p in folder.iterdir()) == [
        "image1.png",
        "img1.png",
        "notes.txt",
    ]
    assert (folder / "img1.png").read_bytes() == b"new"
    assert sentinel.read_text() == "ORIGINAL"


def test_finish_without_overwrite_removes_nothing(tmp_path):
    folder = tmp_path / "out" / "images" / "deck"
    folder.mkdir(parents=True)
    (folder / "img5.png").write_bytes(b"old")

    w = _writer(tmp_path)
    w.write_png(1, _Png())
    w.finish()

    assert (folder / "img5.png").exists()


def test_finish_with_overwrite_and_no_folder_creates_nothing(tmp_path):
    w = _writer(tmp_path, overwrite=True)
    w.finish()

    assert not (tmp_path / "out" / "images").exists()


@pytest.mark.parametrize("linked", ["images", "images/deck"])
def test_a_folder_that_leaves_the_output_dir_is_refused(tmp_path, capsys, linked):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    out = tmp_path / "out"
    link = out / linked
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(outside, link)

    w = ImageWriter(out, "deck", overwrite=True)

    assert w.write_png(1, _Png()) is None
    w.finish()
    assert not list(outside.rglob("img*"))
    assert "refusing" in capsys.readouterr().err
