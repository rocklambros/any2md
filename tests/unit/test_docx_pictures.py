"""DOCX pictures: the alt-text and caption reader, and the mammoth lane.

These run without Docling. The Docling lane is covered in
``tests/integration/test_docx_pictures_docling.py``.
"""

from __future__ import annotations

import zipfile

import any2md.converters.docx as docx_mod
from any2md._safe_open import SourceFile
from any2md.converters._office_pictures import WordPicture, read_alt_texts
from any2md.pipeline import PipelineOptions
from tests._office_fixtures import DocPicture, build_docx, tiny_png


def test_reader_lists_word_pictures_in_document_order(tmp_path):
    doc = build_docx(
        tmp_path / "d.docx",
        [
            "Intro.",
            DocPicture(alt="Architecture  diagram\n"),
            DocPicture(title="Only a title"),
            DocPicture(alt="Has both", title="ignored"),
            DocPicture(caption="Figure 4: Data flow"),
            DocPicture(),
        ],
    )

    alt = read_alt_texts(SourceFile.from_path(doc), "docx")

    assert alt.in_order == [
        WordPicture(alt="Architecture diagram"),
        WordPicture(alt="Only a title"),
        WordPicture(alt="Has both"),
        WordPicture(caption="Figure 4: Data flow"),
        WordPicture(),
    ]


def test_reader_takes_only_a_caption_styled_paragraph(tmp_path):
    doc = build_docx(
        tmp_path / "d.docx",
        [DocPicture(alt="A"), "A plain paragraph is not a caption."],
    )

    alt = read_alt_texts(SourceFile.from_path(doc), "docx")

    assert alt.in_order == [WordPicture(alt="A")]


def _mammoth(tmp_path, blocks, **opts):
    src = build_docx(tmp_path / "report.docx", blocks)
    out = tmp_path / "out"
    assert docx_mod.convert_docx(
        src, out, options=PipelineOptions(backend="mammoth", **opts), force=True
    )
    text = (out / "report.md").read_text(encoding="utf-8")
    return out, text[text.index("\n---\n", 4) + 5 :]


_BLOCKS = [
    "Intro.",
    DocPicture(alt="Architecture diagram"),
    DocPicture(caption="Figure 2: Data flow"),
    DocPicture(),
    DocPicture(alt="Linked logo", linked=True),
    "End.",
]


def test_mammoth_lane_writes_figure_lines_without_reading_images(tmp_path, monkeypatch):
    opened = []
    real_open = zipfile.ZipFile.open

    def spy(self, name, *args, **kwargs):
        if (args[0] if args else kwargs.get("mode", "r")) == "r":
            opened.append(getattr(name, "filename", name))
        return real_open(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", spy)

    out, body = _mammoth(tmp_path, _BLOCKS)

    assert "*Figure: Architecture diagram*" in body
    assert "*Figure: Figure 2: Data flow*" in body
    assert "*Figure: Linked logo*" in body
    assert body.count("Data flow") == 1
    assert body.count("*Figure:") == 3
    assert "](" not in body
    assert "data:" not in body
    assert not (out / "images").exists()
    # Alt text needs no image bytes, so no media part is read.
    assert not [n for n in opened if str(n).startswith("word/media/")]


def test_mammoth_lane_save_images_writes_embedded_images_only(tmp_path):
    out, body = _mammoth(tmp_path, _BLOCKS, save_images=True)

    folder = out / "images" / "report"
    assert sorted(p.name for p in folder.iterdir()) == [
        "img1.png",
        "img2.png",
        "img3.png",
    ]
    assert (folder / "img1.png").read_bytes() == tiny_png()
    assert (
        "*Figure: Architecture diagram*\n\n"
        "![Architecture diagram](images/report/img1.png)"
    ) in body
    assert "![](images/report/img3.png)" in body
    # The linked picture keeps its figure line but has no file to link:
    # external file access stays off.
    assert "*Figure: Linked logo*" in body
    assert "img4" not in body
    assert "data:" not in body


def test_mammoth_identical_pictures_each_get_a_saved_and_linked_file(tmp_path):
    """Invariant: the set of saved files equals the set of linked files."""
    from any2md.pipeline.structured import _IMG_LINK_RE

    out, body = _mammoth(
        tmp_path,
        ["A.", DocPicture(alt="Plan [v2]"), DocPicture(alt="Plan [v2]"), "B."],
        save_images=True,
    )

    links = [m.group(2) for m in _IMG_LINK_RE.finditer(body)]
    saved = {f"images/report/{p.name}" for p in (out / "images" / "report").iterdir()}
    assert len(links) == len(set(links)) == 2
    assert set(links) == saved


def test_mammoth_force_rerun_drops_stale_images(tmp_path):
    _mammoth(tmp_path, _BLOCKS, save_images=True)

    # The document lost two pictures. A --force run removes their files.
    out, body = _mammoth(
        tmp_path, ["Intro.", DocPicture(alt="Only one")], save_images=True
    )

    folder = out / "images" / "report"
    assert sorted(p.name for p in folder.iterdir()) == ["img1.png"]
    assert "![Only one](images/report/img1.png)" in body


def test_mammoth_without_safe_external_access_saves_no_images(tmp_path, monkeypatch):
    """A mammoth release before 1.11 cannot refuse linked files, so no
    image is read at all, and alt text still gives figure lines."""
    monkeypatch.setattr(docx_mod, "_mammoth_blocks_external_files", lambda: False)

    out, body = _mammoth(tmp_path, _BLOCKS, save_images=True)

    assert not (out / "images").exists()
    assert "*Figure: Architecture diagram*" in body
    assert "](" not in body


def test_short_figure_line_survives_the_text_lane(tmp_path):
    """T10 drops short lines after a sentence, but never a figure line."""
    _, body = _mammoth(tmp_path, ["A full sentence.", DocPicture(alt="Chart"), "End."])

    assert "*Figure: Chart*" in body


def test_mammoth_alt_text_brackets_are_escaped(tmp_path):
    _, body = _mammoth(tmp_path, [DocPicture(alt="Plan [draft] v2")])

    assert "*Figure: Plan \\[draft\\] v2*" in body


def test_reader_on_a_broken_package_finds_none(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"PK\x03\x04 not a zip archive")

    assert read_alt_texts(SourceFile.from_path(bad), "docx").in_order is None
