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


def _writer(tmp_path, overwrite=False, name="deck.pptx"):
    return ImageWriter(tmp_path / "out", name, overwrite=overwrite)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Report v2.pptx", "Report.v2.pptx"),
        ("报告.pptx", "会议.pptx"),
        ("a (1).docx", "a 1.docx"),
    ],
)
def test_distinct_markdown_names_get_distinct_folders(tmp_path, first, second):
    """The folder follows the output .md name, which #60 keeps unique per
    run, so two inputs never share (or, under --force, clean) a folder."""
    one = ImageWriter(tmp_path / "out", first, overwrite=True)
    two = ImageWriter(tmp_path / "out", second, overwrite=True)
    one.write_png(1, _Png(b"one"))
    one.commit()
    two.write_png(1, _Png(b"two"))
    two.commit()

    folders = sorted((tmp_path / "out" / "images").iterdir())
    assert len(folders) == 2
    assert sorted((f / "img1.png").read_bytes() for f in folders) == [b"one", b"two"]


def test_links_are_url_encoded(tmp_path):
    w = ImageWriter(tmp_path / "out", "报告 (v2).pptx", overwrite=False)

    link = w.write_png(1, _Png())
    w.commit()

    assert link == "images/%E6%8A%A5%E5%91%8A_%28v2%29/img1.png"
    assert (tmp_path / "out" / "images" / "报告_(v2)" / "img1.png").exists()


def test_a_dot_dot_name_stays_inside_the_output_dir(tmp_path):
    # sanitize_filename("...pdf") is "...md", whose stem is "..".
    w = ImageWriter(tmp_path / "out", "...pdf", overwrite=True)

    link = w.write_png(1, _Png())
    w.commit()

    assert link == "images/_../img1.png"
    assert (tmp_path / "out" / "images" / "_.." / "img1.png").exists()


def _folder(tmp_path):
    return tmp_path / "out" / "images" / "deck"


def test_writes_png_and_bytes_and_returns_links(tmp_path):
    w = _writer(tmp_path)

    assert w.write_png(1, _Png(b"one")) == "images/deck/img1.png"
    assert w.write_bytes(2, "jpg", b"two") == "images/deck/img2.jpg"
    w.commit()

    folder = _folder(tmp_path)
    assert (folder / "img1.png").read_bytes() == b"one"
    assert (folder / "img2.jpg").read_bytes() == b"two"
    # Atomic writes leave no temporary files behind.
    assert sorted(p.name for p in folder.iterdir()) == ["img1.png", "img2.jpg"]


def test_nothing_is_published_before_commit(tmp_path):
    w = _writer(tmp_path)
    w.write_png(1, _Png())

    assert not list(_folder(tmp_path).glob("img*"))


@pytest.mark.parametrize("overwrite", [False, True])
def test_discard_removes_staged_files_and_keeps_old_ones(tmp_path, overwrite):
    """A conversion that fails after its pictures were staged publishes
    nothing, removes nothing, and leaves no temporary files."""
    folder = _folder(tmp_path)
    folder.mkdir(parents=True)
    (folder / "img2.png").write_bytes(b"old")
    w = _writer(tmp_path, overwrite=overwrite)
    w.write_png(1, _Png())
    w.discard()

    assert sorted(p.name for p in folder.iterdir()) == ["img2.png"]


@pytest.mark.parametrize("overwrite", [False, True])
def test_saving_needs_no_hard_link_support(tmp_path, monkeypatch, overwrite):
    """exFAT, FAT32, and some SMB or FUSE mounts refuse hard links."""

    def no_links(*_args, **_kwargs):
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_links)

    w = _writer(tmp_path, overwrite=overwrite)
    link = w.write_png(1, _Png(b"data"))
    w.commit()

    assert link == "images/deck/img1.png"
    folder = _folder(tmp_path)
    assert (folder / "img1.png").read_bytes() == b"data"
    assert sorted(p.name for p in folder.iterdir()) == ["img1.png"]


def test_without_overwrite_an_existing_file_is_kept(tmp_path):
    folder = _folder(tmp_path)
    folder.mkdir(parents=True)
    (folder / "img1.png").write_bytes(b"prior")

    w = _writer(tmp_path)
    link = w.write_png(1, _Png(b"new"))
    w.commit()

    assert link == "images/deck/img1.png"
    assert (folder / "img1.png").read_bytes() == b"prior"


def test_with_overwrite_an_existing_file_is_replaced(tmp_path):
    folder = _folder(tmp_path)
    folder.mkdir(parents=True)
    (folder / "img1.png").write_bytes(b"prior")

    w = _writer(tmp_path, overwrite=True)
    w.write_png(1, _Png(b"new"))
    w.commit()

    assert (folder / "img1.png").read_bytes() == b"new"


@pytest.mark.parametrize("overwrite", [False, True])
def test_a_symlink_at_the_target_is_never_written_through(tmp_path, overwrite):
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("ORIGINAL")
    folder = _folder(tmp_path)
    folder.mkdir(parents=True)
    os.symlink(sentinel, folder / "img1.png")

    w = _writer(tmp_path, overwrite=overwrite)
    link = w.write_png(1, _Png(b"new"))
    w.commit()

    assert sentinel.read_text() == "ORIGINAL"
    if overwrite:
        # The link itself is replaced by a regular file.
        assert not os.path.islink(folder / "img1.png")
        assert (folder / "img1.png").read_bytes() == b"new"
        assert link == "images/deck/img1.png"
    else:
        assert os.path.islink(folder / "img1.png")
        assert link is None


def test_commit_with_overwrite_removes_stale_images_only(tmp_path):
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("ORIGINAL")
    folder = _folder(tmp_path)
    folder.mkdir(parents=True)
    for name in ("img1.png", "img2.png", "img3.jpg", "notes.txt", "image1.png"):
        (folder / name).write_bytes(b"old")
    os.symlink(sentinel, folder / "img9.png")

    w = _writer(tmp_path, overwrite=True)
    w.write_png(1, _Png(b"new"))
    w.commit()

    assert sorted(p.name for p in folder.iterdir()) == [
        "image1.png",
        "img1.png",
        "notes.txt",
    ]
    assert (folder / "img1.png").read_bytes() == b"new"
    assert sentinel.read_text() == "ORIGINAL"


def test_commit_without_overwrite_removes_nothing(tmp_path):
    folder = _folder(tmp_path)
    folder.mkdir(parents=True)
    (folder / "img5.png").write_bytes(b"old")

    w = _writer(tmp_path)
    w.write_png(1, _Png())
    w.commit()

    assert (folder / "img5.png").exists()


def test_commit_with_overwrite_and_no_folder_creates_nothing(tmp_path):
    w = _writer(tmp_path, overwrite=True)
    w.commit()

    assert not (tmp_path / "out" / "images").exists()


@pytest.mark.parametrize("linked", ["images", "images/deck"])
def test_a_folder_that_leaves_the_output_dir_is_refused(tmp_path, capsys, linked):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    out = tmp_path / "out"
    link = out / linked
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(outside, link)

    w = ImageWriter(out, "deck.pptx", overwrite=True)

    assert w.write_png(1, _Png()) is None
    w.commit()
    assert not list(outside.rglob("img*"))
    assert "refusing" in capsys.readouterr().err
