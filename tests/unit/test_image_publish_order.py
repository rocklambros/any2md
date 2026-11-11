"""--save-images publishes images only after the Markdown is written.

Under --force, publishing also removes stale ``imgN`` files. If that ran
before the ``.md`` write, a failed write would leave the old Markdown
linking deleted images. If it ran before the pipeline, a link a pipeline
stage removed would still publish its file.
"""

from __future__ import annotations

import any2md.converters.docx as docx_mod
import any2md.converters.pdf as pdf_mod
from any2md.pipeline import PipelineOptions
from tests._office_fixtures import DocPicture, build_docx


def _old_output(out, stem):
    """An earlier run's output: Markdown linking two images."""
    folder = out / "images" / stem
    folder.mkdir(parents=True)
    (folder / "img1.png").write_bytes(b"OLD1")
    (folder / "img2.png").write_bytes(b"OLD2")
    md = out / f"{stem}.md"
    md.write_text("old body\n", encoding="utf-8")
    return folder, md


def _failing_write(*_args, **_kwargs):
    raise OSError("disk full")


def _drop_image_lines(real_run):
    def run(md_text, lane, options):
        md_text, warnings = real_run(md_text, lane, options)
        kept = [line for line in md_text.split("\n") if "](images/" not in line]
        return "\n".join(kept), warnings

    return run


# ---- DOCX, mammoth lane ------------------------------------------------


def _docx(tmp_path):
    return build_docx(
        tmp_path / "report.docx", ["Intro.", DocPicture(alt="Chart"), "End."]
    )


def _convert_docx(src, out):
    return docx_mod.convert_docx(
        src,
        out,
        options=PipelineOptions(backend="mammoth", save_images=True),
        force=True,
    )


def test_docx_failed_write_keeps_old_images(tmp_path, monkeypatch):
    out = tmp_path / "out"
    folder, md = _old_output(out, "report")
    monkeypatch.setattr(docx_mod, "atomic_write_text", _failing_write)

    assert _convert_docx(_docx(tmp_path), out) is False

    assert md.read_text(encoding="utf-8") == "old body\n"
    assert (folder / "img1.png").read_bytes() == b"OLD1"
    assert (folder / "img2.png").read_bytes() == b"OLD2"
    assert sorted(p.name for p in folder.iterdir()) == ["img1.png", "img2.png"]


def test_docx_link_removed_by_pipeline_publishes_no_file(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr(
        docx_mod.pipeline, "run", _drop_image_lines(docx_mod.pipeline.run)
    )

    assert _convert_docx(_docx(tmp_path), out)

    assert "](images/" not in (out / "report.md").read_text(encoding="utf-8")
    folder = out / "images" / "report"
    assert not folder.exists() or list(folder.iterdir()) == []


# ---- PDF, Docling lane -------------------------------------------------


def _fake_pdf_docling(src, options, writer=None, data=None, capture=None):
    """Stage one image the way the real lane does and link it."""
    link = writer.write_bytes(1, "png", b"NEW1") if writer is not None else None
    body = "# Title\n\nA full sentence about the chart below.\n\n"
    if link:
        body += f"![Chart]({link})\n"
    return body, "docling"


def _convert_pdf(fixture_dir, out):
    return pdf_mod.convert_pdf(
        fixture_dir / "multi_column.pdf",
        out,
        options=PipelineOptions(save_images=True),
        force=True,
    )


def test_pdf_failed_write_keeps_old_images(fixture_dir, tmp_path, monkeypatch):
    out = tmp_path / "out"
    folder, md = _old_output(out, "multi_column")
    monkeypatch.setattr(pdf_mod, "has_docling", lambda: True)
    monkeypatch.setattr(pdf_mod, "_extract_via_docling", _fake_pdf_docling)
    monkeypatch.setattr(pdf_mod, "atomic_write_text", _failing_write)

    assert _convert_pdf(fixture_dir, out) is False

    assert md.read_text(encoding="utf-8") == "old body\n"
    assert (folder / "img1.png").read_bytes() == b"OLD1"
    assert (folder / "img2.png").read_bytes() == b"OLD2"
    assert sorted(p.name for p in folder.iterdir()) == ["img1.png", "img2.png"]


def test_pdf_publishes_linked_image_after_write(fixture_dir, tmp_path, monkeypatch):
    out = tmp_path / "out"
    folder, _md = _old_output(out, "multi_column")
    monkeypatch.setattr(pdf_mod, "has_docling", lambda: True)
    monkeypatch.setattr(pdf_mod, "_extract_via_docling", _fake_pdf_docling)

    assert _convert_pdf(fixture_dir, out)

    assert "](images/multi_column/img1.png)" in (out / "multi_column.md").read_text(
        encoding="utf-8"
    )
    # The new img1 replaces the old one, and the stale img2 is gone.
    assert sorted(p.name for p in folder.iterdir()) == ["img1.png"]
    assert (folder / "img1.png").read_bytes() == b"NEW1"


def test_pdf_link_removed_by_pipeline_publishes_no_file(
    fixture_dir, tmp_path, monkeypatch
):
    out = tmp_path / "out"
    monkeypatch.setattr(pdf_mod, "has_docling", lambda: True)
    monkeypatch.setattr(pdf_mod, "_extract_via_docling", _fake_pdf_docling)
    monkeypatch.setattr(
        pdf_mod.pipeline, "run", _drop_image_lines(pdf_mod.pipeline.run)
    )

    assert _convert_pdf(fixture_dir, out)

    assert "](images/" not in (out / "multi_column.md").read_text(encoding="utf-8")
    folder = out / "images" / "multi_column"
    assert not folder.exists() or list(folder.iterdir()) == []
