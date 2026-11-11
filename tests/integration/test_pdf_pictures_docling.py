"""Integration: PDF pictures through Docling, the same rule as Office files.

A caption Docling links to a picture becomes its ``*Figure:*`` line, and
``--save-images`` writes ``images/<stem>/imgN.png`` and links it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("docling")

import pymupdf  # noqa: E402

from any2md.converters.pdf import convert_pdf  # noqa: E402
from any2md.pipeline import PipelineOptions  # noqa: E402
from tests._office_fixtures import tiny_png  # noqa: E402


def _chart_pdf(tmp_path):
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "A short report about a synthetic chart.", fontsize=12)
    page.insert_image(pymupdf.Rect(150, 120, 450, 400), stream=tiny_png())
    page.insert_text((150, 420), "Figure 1: Synthetic chart", fontsize=10)
    page.insert_text((72, 470), "The text after the figure.", fontsize=12)
    path = tmp_path / "chart.pdf"
    pdf.save(path)
    return path


def _body(md_path):
    text = md_path.read_text(encoding="utf-8")
    return text[text.index("\n---\n", 4) + 5 :]


def test_pdf_caption_becomes_a_figure_line(tmp_path):
    out = tmp_path / "out"

    assert convert_pdf(_chart_pdf(tmp_path), out, options=PipelineOptions())

    body = _body(out / "chart.md")
    assert "*Figure: Figure 1: Synthetic chart*" in body
    assert body.count("Synthetic chart") == 1
    assert "](" not in body
    assert not (out / "images").exists()


def test_pdf_save_images_writes_and_links(tmp_path):
    out = tmp_path / "out"

    assert convert_pdf(
        _chart_pdf(tmp_path), out, options=PipelineOptions(save_images=True)
    )

    body = _body(out / "chart.md")
    assert (out / "images" / "chart" / "img1.png").exists()
    assert (
        "*Figure: Figure 1: Synthetic chart*\n\n"
        "![Figure 1: Synthetic chart](images/chart/img1.png)"
    ) in body
