"""Integration: PowerPoint and Excel files through the real Docling backends."""

from __future__ import annotations

import pytest

pytest.importorskip("docling")

from any2md._safe_open import SourceFile  # noqa: E402
from any2md.converters import convert_file  # noqa: E402
from any2md.pipeline import PipelineOptions  # noqa: E402
from tests._office_fixtures import (  # noqa: E402
    Picture,
    SheetPicture,
    Slide,
    build_pptx,
    build_xlsx,
)


def _split(md_text: str) -> tuple[str, str]:
    end = md_text.index("\n---\n", 4)
    return md_text[:end], md_text[end + 5 :]


def _headings(body: str) -> list[str]:
    return [line for line in body.splitlines() if line.startswith("#")]


def test_pptx_slides_become_sections(tmp_path):
    deck = build_pptx(
        tmp_path / "deck.pptx",
        [
            ("Quarterly Review", "Revenue grew 12 percent."),
            (None, "A slide with no title."),
            ("Next Steps", "Hire two engineers."),
        ],
        title="Q3 Deck",
    )
    out = tmp_path / "out"

    assert convert_file(deck, out, options=PipelineOptions(), force=True)

    fm, body = _split((out / "deck.md").read_text(encoding="utf-8"))
    assert 'type: "pptx"' in fm
    assert 'extracted_via: "docling"' in fm
    assert 'title: "Q3 Deck"' in fm
    assert _headings(body) == [
        "# Q3 Deck",
        "## Quarterly Review",
        "## Slide 2",
        "## Next Steps",
    ]
    assert "Revenue grew 12 percent." in body
    assert "A slide with no title." in body


def test_every_title_placeholder_names_its_slide(tmp_path):
    """Titles below a picture or a text box, centered titles, and titles of
    two paragraphs all become the slide's H2."""
    deck = build_pptx(
        tmp_path / "deck.pptx",
        [
            Slide(title=["Cover"], pictures=[Picture(box=(457200, 0, 914400, 457200))]),
            Slide(title=["Agenda"], title_y=3657600, body="Intro.", body_y=0),
            Slide(title=["Two line", "title"], title_type="ctrTitle", body="B."),
            Slide(body="No title placeholder."),
        ],
    )
    out = tmp_path / "out"

    assert convert_file(deck, out, options=PipelineOptions(), force=True)

    _, body = _split((out / "deck.md").read_text(encoding="utf-8"))
    assert _headings(body) == [
        "# deck",
        "## Cover",
        "## Agenda",
        "## Two line title",
        "## Slide 4",
    ]
    assert "Intro." in body
    assert "No title placeholder." in body


def _picture_deck(tmp_path):
    return build_pptx(
        tmp_path / "deck.pptx",
        [
            Slide(
                title=["Cover"],
                pictures=[Picture(alt="Team logo", box=(457200, 0, 914400, 457200))],
            ),
            Slide(pictures=[Picture(alt="Network map", grouped=True)]),
            Slide(pictures=[Picture()]),
        ],
    )


def test_pptx_picture_alt_text_becomes_figure_lines(tmp_path):
    out = tmp_path / "out"

    assert convert_file(_picture_deck(tmp_path), out, force=True)

    _, body = _split((out / "deck.md").read_text(encoding="utf-8"))
    assert _headings(body) == ["# deck", "## Cover", "## Slide 2", "## Slide 3"]
    assert "## Cover\n\n*Figure: Team logo*" in body
    assert "## Slide 2\n\n*Figure: Network map*" in body
    # Without --save-images no link or placeholder remains.
    assert "](" not in body
    assert "<!--" not in body


def test_xlsx_picture_alt_text_becomes_a_figure_line(tmp_path):
    book = build_xlsx(
        tmp_path / "book.xlsx",
        {"Data": [["k"], ["v"]]},
        pictures={"Data": [SheetPicture(alt="Quarterly trend")]},
    )
    out = tmp_path / "out"

    assert convert_file(book, out, force=True)

    _, body = _split((out / "book.md").read_text(encoding="utf-8"))
    assert "*Figure: Quarterly trend*" in body


def test_save_images_writes_office_pictures(tmp_path):
    out = tmp_path / "out"

    assert convert_file(
        _picture_deck(tmp_path),
        out,
        options=PipelineOptions(save_images=True),
        force=True,
    )

    images = sorted(p.name for p in (out / "images" / "deck").iterdir())
    assert images == ["img1.png", "img2.png", "img3.png"]
    assert (out / "images" / "deck" / "img1.png").read_bytes()[:4] == b"\x89PNG"
    _, body = _split((out / "deck.md").read_text(encoding="utf-8"))
    assert "*Figure: Team logo*\n\n![Team logo](images/deck/img1.png)" in body
    assert "## Slide 3\n\n![](images/deck/img3.png)" in body


def test_off_slide_picture_warning_is_counted_not_printed(tmp_path, capsys):
    """docling-core warns with ``warnings.warn`` when it clamps a box that
    lies outside the slide. The warning is counted, not printed."""
    from any2md.converters import collected_warnings, reset_warnings

    deck = build_pptx(
        tmp_path / "deck.pptx",
        [Slide(title=["Wide"], pictures=[Picture(box=(0, 12000000, 914400, 914400))])],
    )
    reset_warnings()

    assert convert_file(deck, tmp_path / "out", force=True)

    got = collected_warnings()
    reset_warnings()
    assert any("outside page bounds" in w for w in got)
    captured = capsys.readouterr()
    assert "UserWarning" not in captured.err
    assert "warning(s)" in captured.out


def test_identical_pictures_each_get_a_saved_and_linked_file(tmp_path):
    """Invariant: the set of saved files equals the set of linked files.

    Three pictures with the same image bytes, two on one slide and one
    on the next, with brackets in the alt text, which Markdown escapes.
    """
    from any2md.pipeline.structured import _IMG_LINK_RE

    deck = build_pptx(
        tmp_path / "deck.pptx",
        [
            Slide(
                title=["One"],
                pictures=[
                    Picture(alt="Plan [v2]", box=(457200, 0, 914400, 914400)),
                    Picture(alt="Plan [v2]", box=(4572000, 0, 914400, 914400)),
                ],
            ),
            Slide(title=["Two"], pictures=[Picture(alt="Plan [v2]")]),
        ],
    )
    out = tmp_path / "out"

    assert convert_file(
        deck, out, options=PipelineOptions(save_images=True), force=True
    )

    _, body = _split((out / "deck.md").read_text(encoding="utf-8"))
    links = [m.group(2) for m in _IMG_LINK_RE.finditer(body)]
    saved = {f"images/deck/{p.name}" for p in (out / "images" / "deck").iterdir()}
    assert len(links) == len(set(links)) == 3
    assert set(links) == saved
    one, two = body.split("## Two")
    assert [m.group(2) for m in _IMG_LINK_RE.finditer(one)] == [
        "images/deck/img1.png",
        "images/deck/img2.png",
    ]
    assert [m.group(2) for m in _IMG_LINK_RE.finditer(two)] == ["images/deck/img3.png"]


def test_token_export_matches_doclings_own_markdown(tmp_path):
    """export_markdown keeps every export_to_markdown default and changes
    only the picture placeholder, so the rest of the Markdown is Docling's."""
    import re

    from any2md._docling_cache import get_office_converter
    from any2md.converters._office_pictures import export_markdown

    deck = build_pptx(
        tmp_path / "deck.pptx",
        [
            Slide(
                title=["Cover"], pictures=[Picture(alt="Logo")], body="Intro_text <b>."
            ),
            Slide(title=["Two"], body="Body."),
        ],
    )
    doc = get_office_converter("pptx").convert(deck).document

    ours = export_markdown(doc)
    tokens = re.findall(r"<!-- any2md-picture (#/[^ ]+) -->", ours)
    assert tokens == [p.self_ref for p in doc.pictures]
    assert re.sub(r"<!-- any2md-picture #/[^ ]+ -->", "<!-- image -->", ours) == (
        doc.export_to_markdown()
    )


def test_xlsx_sheets_render_as_tables_under_headings(tmp_path):
    book = build_xlsx(
        tmp_path / "budget.xlsx",
        {
            "Revenue": [["Region", "Q1"], ["North", "10"]],
            "Staff": [["Team", "Count"], ["Eng", "5"]],
        },
    )
    out = tmp_path / "out"

    assert convert_file(book, out, options=PipelineOptions(), force=True)

    fm, body = _split((out / "budget.md").read_text(encoding="utf-8"))
    assert 'type: "xlsx"' in fm
    assert _headings(body) == ["# budget", "## Revenue", "## Staff"]
    assert "| Region | Q1 |" in body
    assert "| Eng | 5 |" in body


def test_bytes_backed_source_converts(tmp_path):
    """A scanned file arrives as bytes and reaches Docling as a stream."""
    path = build_xlsx(tmp_path / "scan.xlsx", {"S": [["k", "v"], ["a", "1"]]})
    src = SourceFile("scan.xlsx", data=path.read_bytes(), mtime=0.0)
    path.unlink()
    out = tmp_path / "out"

    assert convert_file(src, out, options=PipelineOptions(), force=True)
    assert "| a | 1 |" in (out / "scan.md").read_text(encoding="utf-8")


def test_content_not_matching_extension_is_rejected(tmp_path, capsys):
    """A workbook renamed to .pptx must not reach another Docling backend."""
    book = build_xlsx(tmp_path / "real.xlsx", {"S": [["a"]]})
    fake = tmp_path / "fake.pptx"
    fake.write_bytes(book.read_bytes())

    assert convert_file(fake, tmp_path / "out", force=True) is False
    assert "FAIL: fake.pptx -- Docling could not convert" in capsys.readouterr().err


def test_corrupt_file_fails_cleanly(tmp_path, capsys):
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"PK\x03\x04 truncated archive")

    assert convert_file(bad, tmp_path / "out", force=True) is False
    # Docling logs its own complaint to stderr as well, so look for the
    # one FAIL line any2md writes.
    fails = [
        line
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("  FAIL: ")
    ]
    assert len(fails) == 1
    # The zip guard refuses it before Docling opens it.
    assert fails[0] == "  FAIL: bad.xlsx -- not a valid OOXML (zip) archive"
