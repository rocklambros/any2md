"""Integration: DOCX pictures through Docling's Word backend."""

from __future__ import annotations

import pytest

pytest.importorskip("docling")

from any2md.converters.docx import convert_docx  # noqa: E402
from any2md.pipeline import PipelineOptions  # noqa: E402
from tests._office_fixtures import DocPicture, build_docx  # noqa: E402


def _body(md_path):
    text = md_path.read_text(encoding="utf-8")
    return text[text.index("\n---\n", 4) + 5 :]


def _doc(tmp_path):
    return build_docx(
        tmp_path / "report.docx",
        [
            "Intro.",
            DocPicture(alt="Architecture diagram"),
            DocPicture(caption="Figure 2: Data flow"),
            DocPicture(title="Logo"),
            DocPicture(),
            "End.",
        ],
    )


def _convert(tmp_path, **opts):
    out = tmp_path / "out"
    assert convert_docx(
        _doc(tmp_path),
        out,
        options=PipelineOptions(backend="docling", **opts),
        force=True,
    )
    return out, _body(out / "report.md")


def test_docling_lane_writes_figure_lines(tmp_path):
    _, body = _convert(tmp_path)

    assert "*Figure: Architecture diagram*" in body
    assert "*Figure: Figure 2: Data flow*" in body
    assert "*Figure: Logo*" in body
    # The caption paragraph becomes the figure line, so it is not repeated.
    assert body.count("Data flow") == 1
    assert body.count("*Figure:") == 3
    assert "](" not in body
    assert "<!--" not in body


def test_failed_docling_lane_leaves_only_the_mammoth_images(tmp_path, monkeypatch):
    """Docling stages its pictures, then fails. The mammoth fallback's
    files are the only ones published, and each one is linked."""
    import any2md.converters.docx as docx_mod
    from any2md.pipeline.structured import _IMG_LINK_RE
    from tests._office_fixtures import tiny_png

    def broken_fill(*_args, **_kwargs):
        raise RuntimeError("fill broke")

    monkeypatch.setattr(docx_mod, "fill_pictures", broken_fill)
    out = tmp_path / "out"

    assert convert_docx(
        _doc(tmp_path), out, options=PipelineOptions(save_images=True), force=False
    )

    body = _body(out / "report.md")
    assert 'extracted_via: "mammoth+markdownify"' in (out / "report.md").read_text()
    links = {m.group(2) for m in _IMG_LINK_RE.finditer(body)}
    folder = out / "images" / "report"
    saved = {f"images/report/{p.name}" for p in folder.iterdir()}
    assert links == saved
    # mammoth keeps the package's own bytes, Docling would re-encode them.
    assert (folder / "img1.png").read_bytes() == tiny_png()


def test_docling_lane_save_images_writes_and_links(tmp_path):
    out, body = _convert(tmp_path, save_images=True)

    images = sorted(p.name for p in (out / "images" / "report").iterdir())
    assert images == ["img1.png", "img2.png", "img3.png", "img4.png"]
    assert (out / "images" / "report" / "img1.png").read_bytes()[:4] == b"\x89PNG"
    assert (
        "*Figure: Architecture diagram*\n\n"
        "![Architecture diagram](images/report/img1.png)"
    ) in body
    assert "![](images/report/img4.png)" in body
