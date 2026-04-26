"""Tests for S1 — lift_figure_captions."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.structured import lift_figure_captions


def test_lifts_caption_from_image_alt():
    text = "Body para.\n\n![A diagram of the system](image_3.png)\n\nMore body.\n"
    out = lift_figure_captions(text, PipelineOptions())
    assert "*Figure: A diagram of the system*" in out
    assert "image_3.png" not in out  # image link dropped


def test_save_images_preserves_link():
    text = "![A diagram](image.png)\n"
    out = lift_figure_captions(text, PipelineOptions(save_images=True))
    assert "image.png" in out


def test_lifts_html_figure_tag_with_figcaption():
    text = (
        "<figure>\n"
        "<img src='x.png' alt='diagram'/>\n"
        "<figcaption>Threat model overview</figcaption>\n"
        "</figure>\n"
    )
    out = lift_figure_captions(text, PipelineOptions())
    assert "*Figure: Threat model overview*" in out


def test_no_match_is_noop():
    text = "Just regular paragraphs here.\nNothing special.\n"
    assert lift_figure_captions(text, PipelineOptions()) == text


def test_html_comment_image_placeholder_stripped():
    # Docling sometimes emits <!-- image --> as a placeholder
    text = "Para before.\n\n<!-- image -->\n\nPara after.\n"
    out = lift_figure_captions(text, PipelineOptions())
    assert "<!-- image -->" not in out
