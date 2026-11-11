"""DOCX pictures: the alt-text and caption reader, and the mammoth lane.

These run without Docling. The Docling lane is covered in
``tests/integration/test_docx_pictures_docling.py``.
"""

from __future__ import annotations

from any2md._safe_open import SourceFile
from any2md.converters._office_pictures import WordPicture, read_alt_texts
from tests._office_fixtures import DocPicture, build_docx


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


def test_reader_on_a_broken_package_finds_none(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"PK\x03\x04 not a zip archive")

    assert read_alt_texts(SourceFile.from_path(bad), "docx").in_order is None
