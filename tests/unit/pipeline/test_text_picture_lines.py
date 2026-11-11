"""Text-lane stages never drop a picture's figure line or image link.

The mammoth lane writes a picture as ``*Figure: text*`` and, under
--save-images, an image link on the next line. A picture without alt
text gets the bare link ``![](images/<stem>/imgN.png)``, which is short
enough to look like a fragment. Dropping it leaves a saved file that
nothing links, or a figure line with no image.
"""

from __future__ import annotations

import pytest

import any2md.converters.docx as docx_mod
from any2md.pipeline import PipelineOptions
from any2md.pipeline.text import (
    dedupe_paragraphs,
    strip_cover_artifacts,
    strip_running_headers_footers,
    strip_web_fragments,
)
from tests._office_fixtures import DocPicture, build_docx

AGGR = PipelineOptions(profile="aggressive")

_PICTURE_LINES = [
    "![](images/a/img1.png)",
    "![x](a.png)",
    "[![](images/a/img1.png)](https://example.com)",
    "*Figure: Chart*",
]


@pytest.mark.parametrize("line", _PICTURE_LINES)
def test_t10_keeps_a_short_picture_line_after_a_sentence(line):
    text = f"A full sentence.\n\n{line}\n\nMore text follows here.\n"
    assert line in strip_web_fragments(text, AGGR).split("\n")


def test_t10_still_drops_a_short_fragment():
    text = "A full sentence.\n\nfragment text\n\nMore text follows here.\n"
    assert "fragment text" not in strip_web_fragments(text, AGGR)


@pytest.mark.parametrize("line", _PICTURE_LINES)
def test_t3_keeps_a_repeated_picture_line(line):
    # Two pictures in a row with the same alt text give the same figure
    # line twice. Each one stands for its own picture.
    text = f"Intro.\n\n{line}\n\n{line}\n\nEnd.\n"
    assert dedupe_paragraphs(text, AGGR).count(line) == 2


def test_t3_still_drops_a_repeated_paragraph():
    text = "Intro.\n\nSame words.\n\nSame words.\n\nEnd.\n"
    assert dedupe_paragraphs(text, AGGR).count("Same words.") == 1


@pytest.mark.parametrize("line", ["![](images/a/img1.png)", "*Figure: Logo*"])
def test_t5_keeps_a_picture_repeated_at_page_edges(line):
    pages = [f"{line}\nBody of page {n}.\n" for n in range(1, 4)]
    out = strip_running_headers_footers("\f".join(pages), PipelineOptions())
    assert out.count(line) == 3


def test_t8_keeps_a_picture_on_the_cover():
    text = (
        "# Title\n\n"
        "*Figure: Scan the QR code for the survey*\n\n"
        "![Scan the QR code for the survey](images/a/img1.png)\n\n"
        "## Real Section\n\nBody.\n"
    )
    out = strip_cover_artifacts(text, AGGR)
    assert "*Figure: Scan the QR code for the survey*" in out
    assert "![Scan the QR code for the survey](images/a/img1.png)" in out


def test_mammoth_picture_without_alt_text_after_a_sentence_keeps_its_link(tmp_path):
    # A short stem keeps the bare link under T10's 25-character limit.
    src = build_docx(
        tmp_path / "r.docx",
        ["A full sentence.", DocPicture(), "More text follows here."],
    )
    out = tmp_path / "out"
    assert docx_mod.convert_docx(
        src,
        out,
        options=PipelineOptions(
            backend="mammoth", save_images=True, profile="aggressive"
        ),
        force=True,
    )

    body = (out / "r.md").read_text(encoding="utf-8")
    assert "![](images/r/img1.png)" in body
    assert (out / "images" / "r" / "img1.png").exists()
