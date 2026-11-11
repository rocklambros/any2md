"""PowerPoint and Excel input: dispatch, failure paths, and Markdown shape.

These tests run without Docling. A fake DoclingDocument stands in for
the converter output so the section and heading logic is checked on
every install. Real conversions live in
``tests/integration/test_office_docling.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import NamedTuple

import pytest

import any2md._docling_cache as docling_cache
import any2md.converters.office as office
from any2md._docling import INSTALL_CMD
from any2md._safe_open import SourceFile
from any2md.converters import SUPPORTED_EXTENSIONS, convert_file
from any2md.converters._office_pictures import picture_token
from any2md.pipeline import PipelineOptions
from tests._office_fixtures import (
    Picture,
    SheetPicture,
    Slide,
    build_pptx,
    build_xlsx,
)


class _Label(NamedTuple):
    """Hashable like docling-core's label enum, with the same ``value``."""

    value: str


def _label(value):
    return _Label(value)


# What ``office._split_labels`` returns from docling-core, by value.
_TITLE_LABELS = {_label("title")}
_BODY_LABELS = {_label(v) for v in ("paragraph", "list_item", "table", "picture")}


@pytest.fixture(autouse=True)
def _fake_export_labels(monkeypatch):
    monkeypatch.setattr(office, "_split_labels", lambda: (_TITLE_LABELS, _BODY_LABELS))


_BBOX = SimpleNamespace(l=0.0, t=0.0, r=1.0, b=1.0)


class _FakeImage:
    """Stands in for a PIL image: ``save`` writes fixed bytes."""

    def __init__(self, tag: bytes = b""):
        self._tag = tag

    def save(self, fp, format):
        fp.write(b"PNG:" + format.encode() + self._tag)


def _picture(
    caption="", description="", box=None, image=None, sheet=None, no_token=False
):
    """A picture item with the fields ``_office_pictures`` reads."""
    item = SimpleNamespace(
        label=_label("picture"),
        captions=[object()] if caption else [],
        caption_text=lambda doc: caption,
        meta=SimpleNamespace(description=SimpleNamespace(text=description))
        if description
        else None,
        get_image=lambda doc: image,
        parent=SimpleNamespace(resolve=lambda doc: SimpleNamespace(name=sheet)),
        prov=[],
        box=box,
        no_token=no_token,
    )
    return item


class _FakeDoc:
    """The slice of DoclingDocument that ``office`` reads.

    ``pages`` maps page number to Markdown, or to a list of items: a
    ``(label, text)`` pair or a ``_picture`` object. A "title" item
    renders as ``# text`` and a picture as the image placeholder, the
    way Docling writes them. Every item carries a provenance entry for
    its page unless listed in ``orphans``.
    """

    def __init__(self, pages, sheet_names=(), orphans=0, page_filter=True):
        self._pages = {
            n: [("paragraph", spec)] if isinstance(spec, str) else list(spec)
            for n, spec in dict(pages).items()
        }
        self.pages = {n: object() for n in self._pages}
        self.groups = [
            SimpleNamespace(name=n, label=_label("sheet")) for n in sheet_names
        ]
        self._items = []
        for n, items in self._pages.items():
            for spec in items:
                if isinstance(spec, tuple):
                    label, text = spec
                    spec = SimpleNamespace(label=_label(label), text=text, prov=[])
                if not spec.prov:
                    box = getattr(spec, "box", None)
                    bbox = (
                        SimpleNamespace(l=box[0], t=box[1], r=box[2], b=box[3])
                        if box
                        else _BBOX
                    )
                    spec.prov = [SimpleNamespace(page_no=n, bbox=bbox)]
                if not getattr(spec, "self_ref", None):
                    spec.self_ref = f"#/items/{len(self._items)}"
                self._items.append(spec)
        self._items += [
            SimpleNamespace(label=_label("paragraph"), text="", prov=[])
        ] * orphans
        self._page_filter = page_filter

    @property
    def pictures(self):
        return [i for i in self._items if i.label.value == "picture"]

    def iterate_items(self, page_no=None, **_kwargs):
        for item in self._items:
            if page_no is None or (item.prov and item.prov[0].page_no == page_no):
                yield item, 1

    def _render(self, item, kwargs):
        label = item.label.value
        if label == "title":
            return f"# {item.text}"
        if label == "section_header":
            return f"## {item.text}"
        if label == "picture":
            # What the token-writing picture serializer writes, unless the
            # picture is one Docling leaves out of the Markdown.
            return (
                "" if getattr(item, "no_token", False) else picture_token(item.self_ref)
            )
        return item.text

    def export_to_markdown(self, **kwargs):
        page_no = kwargs.get("page_no")
        if page_no is not None and not self._page_filter:
            raise TypeError("unexpected keyword argument 'page_no'")
        allowed = kwargs.get("labels")
        wanted = None if allowed is None else {lab.value for lab in allowed}
        parts = [
            self._render(item, kwargs)
            for item, _ in self.iterate_items(page_no=page_no)
            if wanted is None or item.label.value in wanted
        ]
        return "\n\n".join(p for p in parts if p)


def _fake_docling(monkeypatch, doc):
    """Make ``office`` believe Docling is installed and returns ``doc``."""
    seen: list[SourceFile] = []

    def fake_convert(src, fmt, capture=None):
        seen.append(src)
        return doc

    monkeypatch.setattr(office, "has_docling", lambda: True)
    monkeypatch.setattr(office, "_convert_via_docling", fake_convert)
    return seen


def _body(md_path: Path) -> str:
    text = md_path.read_text(encoding="utf-8")
    return text[text.index("\n---\n", 4) + 5 :]


def _frontmatter(md_path: Path) -> str:
    text = md_path.read_text(encoding="utf-8")
    return text[: text.index("\n---\n", 4)]


# ---- dispatch ----------------------------------------------------------


def test_extensions_are_supported():
    assert {".pptx", ".xlsx"} <= SUPPORTED_EXTENSIONS


@pytest.mark.parametrize(
    ("name", "fmt"),
    [("deck.pptx", "pptx"), ("book.xlsx", "xlsx"), ("LOUD.PPTX", "pptx")],
)
def test_convert_file_dispatches_to_office(monkeypatch, tmp_path, name, fmt):
    calls = []

    def fake(source, output_dir, got_fmt, options=None, force=False):
        calls.append((source.name, got_fmt))
        return True

    monkeypatch.setattr(office, "convert_office", fake)
    assert convert_file(tmp_path / name, tmp_path / "out", force=True)
    assert calls == [(name, fmt)]


# ---- failure paths -----------------------------------------------------


@pytest.mark.parametrize("fmt", ["pptx", "xlsx"])
def test_missing_docling_fails_file_with_install_hint(
    monkeypatch, tmp_path, capsys, fmt
):
    monkeypatch.setattr(office, "has_docling", lambda: False)
    src = tmp_path / f"in.{fmt}"
    src.write_bytes(b"PK")
    out = tmp_path / "out"

    assert office.convert_office(src, out, fmt, force=True) is False

    err = capsys.readouterr().err
    assert err.startswith("  FAIL: ")
    assert f"{fmt.upper()} input needs Docling" in err
    assert INSTALL_CMD in err
    assert not out.exists()


def test_failure_line_strips_control_characters(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(office, "has_docling", lambda: False)
    name = "evil\x1b[31m\nFAIL: forged\u202e.pptx"
    src = SourceFile(name, data=b"PK")

    assert office.convert_office(src, tmp_path / "out", "pptx", force=True) is False

    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert "\x1b" not in err
    assert "\u202e" not in err


@pytest.mark.parametrize("backend", ["pymupdf4llm", "mammoth"])
@pytest.mark.parametrize("fmt", ["pptx", "xlsx"])
def test_non_docling_backend_is_rejected(monkeypatch, tmp_path, capsys, backend, fmt):
    seen = _fake_docling(monkeypatch, _FakeDoc({1: "text"}))
    src = tmp_path / f"in.{fmt}"
    src.write_bytes(b"PK")

    ok = office.convert_office(
        src, tmp_path / "out", fmt, options=PipelineOptions(backend=backend)
    )

    assert ok is False
    assert seen == []
    err = capsys.readouterr().err
    assert f"backend '{backend}' is not valid for {fmt.upper()} input" in err


def test_docling_error_fails_only_this_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(office, "has_docling", lambda: True)

    def boom(src, fmt, capture=None):
        raise RuntimeError("Pipeline SimplePipeline failed\nsecond line")

    monkeypatch.setattr(office, "_convert_via_docling", boom)
    src = build_xlsx(tmp_path / "broken.xlsx", {"S": [["a"]]})

    assert office.convert_office(src, tmp_path / "out", "xlsx", force=True) is False

    err = capsys.readouterr().err
    assert "FAIL: broken.xlsx -- Docling could not convert this XLSX file" in err
    assert err.count("\n") == 1


def test_existing_output_is_skipped(monkeypatch, tmp_path, capsys):
    seen = _fake_docling(monkeypatch, _FakeDoc({1: "text"}))
    out = tmp_path / "out"
    out.mkdir()
    (out / "deck.md").write_text("keep")

    assert office.convert_office(tmp_path / "deck.pptx", out, "pptx") is True
    assert seen == []
    assert (out / "deck.md").read_text() == "keep"


def test_unknown_office_format_is_refused():
    with pytest.raises(ValueError):
        docling_cache.get_office_converter("pdf")


def test_docling_receives_path_never_str(monkeypatch, tmp_path):
    """A path-backed source reaches Docling as a Path (a str is a URL)."""
    got = []

    class FakeConverter:
        def convert(self, source):
            got.append(source)
            return SimpleNamespace(document="doc")

    monkeypatch.setattr(
        docling_cache, "get_office_converter", lambda fmt: FakeConverter()
    )
    src = SourceFile.from_path(tmp_path / "http:evil#.pptx")

    assert office._convert_via_docling(src, "pptx") == "doc"
    assert type(got[0]) is not str
    assert isinstance(got[0], Path)


def test_convert_failure_evicts_cache_slot(monkeypatch, tmp_path):
    evicted = []

    class FailingConverter:
        def convert(self, source):
            raise RuntimeError("corrupt")

    monkeypatch.setattr(
        docling_cache, "get_office_converter", lambda fmt: FailingConverter()
    )
    monkeypatch.setattr(
        docling_cache, "evict_on_convert_failure", lambda fmt, opts: evicted.append(fmt)
    )

    with pytest.raises(RuntimeError):
        office._convert_via_docling(SourceFile.from_path(tmp_path / "a.xlsx"), "xlsx")
    assert evicted == ["xlsx"]


# ---- Markdown shape ----------------------------------------------------


def test_slides_share_one_level_under_a_single_h1(monkeypatch, tmp_path):
    deck = build_pptx(tmp_path / "deck.pptx", [("a", "b")], title="Q3 Deck")
    doc = _FakeDoc(
        {
            1: [("title", "Kickoff"), ("paragraph", "Welcome.")],
            2: "Body with no title placeholder.",
            3: [("title", "Results"), ("paragraph", "## Detail\n\nUp 12 percent.")],
        }
    )
    _fake_docling(monkeypatch, doc)
    out = tmp_path / "out"

    assert office.convert_office(deck, out, "pptx", force=True)

    body = _body(out / "deck.md")
    headings = [line for line in body.splitlines() if line.startswith("#")]
    assert headings == [
        "# Q3 Deck",
        "## Kickoff",
        "## Slide 2",
        "## Results",
        "### Detail",
    ]
    fm = _frontmatter(out / "deck.md")
    assert 'title: "Q3 Deck"' in fm
    assert 'type: "pptx"' in fm
    assert 'extracted_via: "docling"' in fm
    assert 'authors: ["Ada Example"]' in fm
    assert 'date: "2026-03-15"' in fm
    assert "word_count:" in fm


def test_each_sheet_gets_a_heading(monkeypatch, tmp_path):
    book = build_xlsx(tmp_path / "budget_2026.xlsx", {"x": [["1"]]})
    table = "| a | b |\n|---|---|\n| 1 | 2 |"
    doc = _FakeDoc(
        {1: table, 2: "", 3: table},
        sheet_names=["Revenue", "Empty", "Staff\nList"],
    )
    _fake_docling(monkeypatch, doc)
    out = tmp_path / "out"

    assert office.convert_office(book, out, "xlsx", force=True)

    body = _body(out / "budget_2026.md")
    headings = [line for line in body.splitlines() if line.startswith("#")]
    # No core title, so the file stem names the workbook. The empty
    # sheet adds no section.
    assert headings == ["# budget 2026", "## Revenue", "## Staff List"]
    assert body.count("| a | b |") == 2
    assert 'type: "xlsx"' in _frontmatter(out / "budget_2026.md")


def test_item_without_page_falls_back_to_whole_document():
    doc = _FakeDoc({1: "# One", 2: "# Two"}, orphans=1)
    assert office._page_sections(doc, "pptx", {}) is None
    md = office._render_markdown(doc, "pptx", "Deck")
    assert md.startswith("# Deck\n\n# One")
    assert "# Two" in md


def test_sheet_count_mismatch_falls_back():
    doc = _FakeDoc({1: "t1", 2: "t2"}, sheet_names=["only one"])
    assert office._page_sections(doc, "xlsx", {}) is None


def test_docling_core_without_page_filter_falls_back():
    doc = _FakeDoc({1: "t1"}, sheet_names=["S"], page_filter=False)
    assert office._page_sections(doc, "xlsx", {}) is None
    assert "t1" in office._render_markdown(doc, "xlsx", "Book")


def test_demote_headings_skips_code_fences():
    md = "# Title\n\n```\n# not a heading\n```\n\n###### Deep"
    assert office._demote_headings(md, 1) == (
        "## Title\n\n```\n# not a heading\n```\n\n###### Deep"
    )


def test_untitled_slide_nests_its_content_under_slide_n():
    doc = _FakeDoc({1: "#hashtag is body text\n\n# Not a placeholder"})
    md = office._render_markdown(doc, "pptx", "Deck")
    assert md == (
        "# Deck\n\n## Slide 1\n\n#hashtag is body text\n\n### Not a placeholder\n"
    )


def test_title_below_other_content_still_names_the_slide():
    """Docling orders shapes by position, so the title need not come first."""
    doc = _FakeDoc(
        {
            1: [_picture(), ("title", "Cover"), ("paragraph", "Subtitle")],
            2: [("paragraph", "Intro."), ("title", "Agenda")],
        }
    )
    md = office._render_markdown(doc, "pptx", "Deck")
    assert md == "# Deck\n\n## Cover\n\nSubtitle\n\n## Agenda\n\nIntro.\n"


def test_title_paragraphs_join_into_one_heading():
    doc = _FakeDoc({1: [("title", "Two line"), ("title", "title"), ("paragraph", "B")]})
    md = office._render_markdown(doc, "pptx", "Deck")
    assert md == "# Deck\n\n## Two line title\n\nB\n"


def test_slide_opening_with_a_subheading_keeps_its_own_section():
    """Only a title placeholder names a slide. A slide whose Markdown opens
    with an H2 (a section header, a subtitle) still gets "Slide N", so it
    never folds into the slide before it."""
    doc = _FakeDoc(
        {
            1: [("title", "Intro"), ("paragraph", "Welcome.")],
            2: [("section_header", "Subtitle"), ("paragraph", "Body.")],
        }
    )
    md = office._render_markdown(doc, "pptx", "Deck")
    assert md == (
        "# Deck\n\n## Intro\n\nWelcome.\n\n## Slide 2\n\n#### Subtitle\n\nBody.\n"
    )


def test_title_only_slide_keeps_its_section():
    doc = _FakeDoc({1: [("title", "Thank you")], 2: "", 3: "Body"})
    md = office._render_markdown(doc, "pptx", "Deck")
    assert md == "# Deck\n\n## Thank you\n\n## Slide 3\n\nBody\n"


# ---- pictures ----------------------------------------------------------


def _convert_with(monkeypatch, tmp_path, doc, fmt="pptx", **opts):
    """Run ``convert_office`` on a fixture with ``doc`` as Docling's output."""
    if fmt == "pptx":
        src = build_pptx(tmp_path / "deck.pptx", [("a", "b")])
    else:
        src = build_xlsx(tmp_path / "deck.xlsx", {"S": [["a"]]})
    _fake_docling(monkeypatch, doc)
    out = tmp_path / "out"
    assert office.convert_office(
        src, out, fmt, options=PipelineOptions(**opts), force=True
    )
    return out, _body(out / "deck.md")


def test_picture_caption_becomes_a_figure_line(monkeypatch, tmp_path):
    doc = _FakeDoc({1: [("title", "Results"), _picture(caption="Revenue by region")]})

    _, body = _convert_with(monkeypatch, tmp_path, doc)

    assert "## Results\n\n*Figure: Revenue by region*" in body
    # The caption moves into the figure line, so it is not repeated.
    assert body.count("Revenue by region") == 1
    assert "<!--" not in body


def test_picture_description_becomes_a_figure_line(monkeypatch, tmp_path):
    doc = _FakeDoc(
        {1: [_picture(description="Logo of the team", sheet="S")]}, sheet_names=["S"]
    )

    _, body = _convert_with(monkeypatch, tmp_path, doc, fmt="xlsx")

    assert "## S\n\n*Figure: Logo of the team*" in body


def test_alt_text_pairs_with_the_picture_at_its_position(monkeypatch, tmp_path):
    deck = build_pptx(
        tmp_path / "deck.pptx",
        [
            Slide(
                title=["Map"],
                pictures=[
                    Picture(alt="Office map", box=(457200, 0, 914400, 457200)),
                    Picture(alt="", box=(4572000, 0, 914400, 457200)),
                ],
            )
        ],
    )
    doc = _FakeDoc(
        {
            1: [
                _picture(box=(4572000, 0, 5486400, 457200)),
                _picture(box=(457200, 0, 1371600, 457200)),
                ("title", "Map"),
            ]
        }
    )
    _fake_docling(monkeypatch, doc)
    out = tmp_path / "out"

    assert office.convert_office(deck, out, "pptx", force=True)

    body = _body(out / "deck.md")
    assert body.count("*Figure:") == 1
    assert "## Map\n\n*Figure: Office map*" in body


def test_caption_wins_over_alt_text(monkeypatch, tmp_path):
    deck = build_pptx(
        tmp_path / "deck.pptx",
        [Slide(pictures=[Picture(alt="Alt", box=(0, 0, 914400, 914400))])],
    )
    doc = _FakeDoc({1: [_picture(caption="Chart title", box=(0, 0, 914400, 914400))]})
    _fake_docling(monkeypatch, doc)
    out = tmp_path / "out"

    assert office.convert_office(deck, out, "pptx", force=True)
    assert "*Figure: Chart title*" in _body(out / "deck.md")


def test_picture_only_slide_keeps_its_section(monkeypatch, tmp_path):
    doc = _FakeDoc(
        {
            1: [("title", "Intro")],
            2: [_picture()],
            3: "",
            4: [_picture(caption="Org chart")],
        }
    )

    _, body = _convert_with(monkeypatch, tmp_path, doc)

    headings = [line for line in body.splitlines() if line.startswith("#")]
    # Slide 3 holds nothing and adds no section. Slide 2 holds a picture
    # without text, so its section stays to show the slide was there.
    assert headings == ["# deck", "## Intro", "## Slide 2", "## Slide 4"]
    assert "## Slide 4\n\n*Figure: Org chart*" in body


def test_a_picture_missing_from_the_markdown_shifts_no_other_figure(
    monkeypatch, tmp_path
):
    """Each token carries its picture's ref. When Docling writes no token
    for one picture, the next picture still gets its own figure and file."""
    doc = _FakeDoc(
        {
            1: [
                _picture(caption="Skipped", image=_FakeImage(b"one"), no_token=True),
                _picture(caption="Shown", image=_FakeImage(b"two")),
            ]
        }
    )

    out, body = _convert_with(monkeypatch, tmp_path, doc, save_images=True)

    assert "*Figure: Shown*\n\n![Shown](images/deck/img2.png)" in body
    assert "Skipped" not in body
    folder = out / "images" / "deck"
    assert (folder / "img2.png").read_bytes() == b"PNG:PNGtwo"
    # Nothing is saved that the Markdown does not link.
    assert sorted(p.name for p in folder.iterdir()) == ["img2.png"]


def test_figure_text_brackets_are_escaped(monkeypatch, tmp_path):
    doc = _FakeDoc({1: [_picture(caption="Plan [draft] v2")]})

    _, body = _convert_with(monkeypatch, tmp_path, doc)

    assert "*Figure: Plan \\[draft\\] v2*" in body


def test_save_images_writes_and_links_each_picture(monkeypatch, tmp_path):
    doc = _FakeDoc(
        {
            1: [_picture(caption="Chart", image=_FakeImage())],
            2: [_picture(image=_FakeImage())],
            3: [_picture(caption="No pixels")],
        }
    )

    out, body = _convert_with(monkeypatch, tmp_path, doc, save_images=True)

    assert (out / "images" / "deck" / "img1.png").read_bytes() == b"PNG:PNG"
    assert (out / "images" / "deck" / "img2.png").exists()
    assert not (out / "images" / "deck" / "img3.png").exists()
    assert "*Figure: Chart*\n\n![Chart](images/deck/img1.png)" in body
    assert "## Slide 2\n\n![](images/deck/img2.png)" in body
    # A picture without image data keeps its figure line and gets no link.
    assert "## Slide 3\n\n*Figure: No pixels*\n" in body
    assert "No pixels](" not in body


def _run_saving(monkeypatch, deck, out, doc, force):
    _fake_docling(monkeypatch, doc)
    return office.convert_office(
        deck, out, "pptx", options=PipelineOptions(save_images=True), force=force
    )


def test_force_regenerates_images_and_drops_stale_ones(monkeypatch, tmp_path):
    deck = build_pptx(tmp_path / "deck.pptx", [("a", "b")])
    out = tmp_path / "out"
    folder = out / "images" / "deck"
    three = _FakeDoc({n: [_picture(image=_FakeImage(b"old"))] for n in (1, 2, 3)})
    assert _run_saving(monkeypatch, deck, out, three, force=True)
    assert sorted(p.name for p in folder.iterdir()) == [
        "img1.png",
        "img2.png",
        "img3.png",
    ]

    # The deck lost two pictures and its first one changed.
    one = _FakeDoc({1: [_picture(image=_FakeImage(b"new"))]})
    assert _run_saving(monkeypatch, deck, out, one, force=True)

    assert sorted(p.name for p in folder.iterdir()) == ["img1.png"]
    assert (folder / "img1.png").read_bytes() == b"PNG:PNGnew"
    assert "img2" not in _body(out / "deck.md")


def _linked_images(body: str) -> list[str]:
    """Image links in ``body``, read with S1's own pattern.

    The pattern honors backslash escapes in the alt text, the way
    CommonMark does, so ``![a \\[b\\]](x)`` counts as a link to ``x``.
    """
    from any2md.pipeline.structured import _IMG_LINK_RE

    return [m.group(2) for m in _IMG_LINK_RE.finditer(body)]


def test_every_saved_image_is_linked_once_and_nothing_else_is_saved(
    monkeypatch, tmp_path
):
    """Identical pictures, on one slide and across slides, each keep their
    own file and link, also with brackets in the alt text."""
    deck = build_pptx(tmp_path / "deck.pptx", [("a", "b")])
    out = tmp_path / "out"
    same = b"same-bytes"
    doc = _FakeDoc(
        {
            1: [
                ("title", "One"),
                _picture(caption="Plan [v2]", image=_FakeImage(same)),
                _picture(caption="Plan [v2]", image=_FakeImage(same)),
            ],
            2: [("title", "Two"), _picture(image=_FakeImage(same))],
        }
    )

    assert _run_saving(monkeypatch, deck, out, doc, force=True)

    body = _body(out / "deck.md")
    links = _linked_images(body)
    saved = {f"images/deck/{p.name}" for p in (out / "images" / "deck").iterdir()}
    assert len(links) == len(set(links)) == 3
    assert set(links) == saved
    # Each link sits in its own slide's section.
    one, two = body.split("## Two")
    assert _linked_images(one) == ["images/deck/img1.png", "images/deck/img2.png"]
    assert _linked_images(two) == ["images/deck/img3.png"]


def test_a_failed_render_publishes_no_images(monkeypatch, tmp_path):
    deck = build_pptx(tmp_path / "deck.pptx", [("a", "b")])
    out = tmp_path / "out"

    def broken_render(*_args, **_kwargs):
        raise RuntimeError("export broke")

    monkeypatch.setattr(office, "_render_markdown", broken_render)
    doc = _FakeDoc({1: [_picture(image=_FakeImage())]})

    assert _run_saving(monkeypatch, deck, out, doc, force=True) is False
    folder = out / "images" / "deck"
    assert not folder.exists() or list(folder.iterdir()) == []


def test_force_with_no_pictures_left_removes_every_old_image(monkeypatch, tmp_path):
    deck = build_pptx(tmp_path / "deck.pptx", [("a", "b")])
    out = tmp_path / "out"
    folder = out / "images" / "deck"
    pictured = _FakeDoc({1: [_picture(image=_FakeImage())]})
    assert _run_saving(monkeypatch, deck, out, pictured, force=True)

    assert _run_saving(monkeypatch, deck, out, _FakeDoc({1: "Text only."}), force=True)

    assert list(folder.iterdir()) == []


def test_without_force_existing_output_leaves_images_alone(monkeypatch, tmp_path):
    deck = build_pptx(tmp_path / "deck.pptx", [("a", "b")])
    out = tmp_path / "out"
    folder = out / "images" / "deck"
    two = _FakeDoc({n: [_picture(image=_FakeImage(b"old"))] for n in (1, 2)})
    assert _run_saving(monkeypatch, deck, out, two, force=True)

    one = _FakeDoc({1: [_picture(image=_FakeImage(b"new"))]})
    assert _run_saving(monkeypatch, deck, out, one, force=False)

    # The Markdown exists, so the file is skipped and nothing is touched.
    assert sorted(p.name for p in folder.iterdir()) == ["img1.png", "img2.png"]
    assert (folder / "img1.png").read_bytes() == b"PNG:PNGold"


def test_without_save_images_nothing_is_written(monkeypatch, tmp_path):
    doc = _FakeDoc({1: [_picture(caption="Chart", image=_FakeImage())]})

    out, body = _convert_with(monkeypatch, tmp_path, doc)

    assert not (out / "images").exists()
    assert "](" not in body


def test_read_alt_texts_maps_group_transforms_and_clamps(tmp_path):
    from any2md.converters._office_pictures import read_alt_texts

    deck = build_pptx(
        tmp_path / "deck.pptx",
        [
            Slide(),
            Slide(
                pictures=[
                    Picture(
                        alt="Grouped", box=(457200, 0, 914400, 914400), grouped=True
                    ),
                    Picture(alt="Off slide", box=(-914400, 0, 1828800, 914400)),
                    Picture(alt="Two  words\n", box=(0, 914400, 914400, 914400)),
                ]
            ),
        ],
    )

    alt = read_alt_texts(SourceFile.from_path(deck), "pptx")

    # The group doubles the picture and moves it one inch right.
    assert alt.take(2, (1371600, 0, 3200400, 1828800)) == "Grouped"
    # Docling clamps a box to the slide, so the key is clamped too.
    assert alt.take(2, (0, 0, 914400, 914400)) == "Off slide"
    assert alt.take(2, (0, 914400, 914400, 1828800)) == "Two words"
    # Each entry pairs once, and a slide without pictures has none.
    assert alt.take(2, (0, 914400, 914400, 1828800)) == ""
    assert alt.take(1, (0, 0, 914400, 914400)) == ""


def test_read_alt_texts_keys_sheet_pictures_by_name_and_cells(tmp_path):
    from any2md.converters._office_pictures import read_alt_texts

    book = build_xlsx(
        tmp_path / "book.xlsx",
        {"Data": [["a"]], "Charts": [["b"]]},
        pictures={"Charts": [SheetPicture(alt="Trend", cells=(1, 2, 4, 9))]},
    )

    alt = read_alt_texts(SourceFile.from_path(book), "xlsx")

    assert alt.take("Data", (1, 2, 5, 10)) == ""
    assert alt.take("Charts", (1, 2, 5, 10)) == "Trend"


def test_read_alt_texts_on_a_broken_package_finds_none(tmp_path):
    from any2md.converters._office_pictures import read_alt_texts

    bad = tmp_path / "bad.pptx"
    bad.write_bytes(b"PK\x03\x04 not a zip archive")

    alt = read_alt_texts(SourceFile.from_path(bad), "pptx")
    assert alt.by_page == {}
    assert alt.warning and "alt text" in alt.warning


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("bad"),
        NotImplementedError("bad"),
        EOFError("bad"),
        KeyError("bad"),
        __import__("zlib").error("bad"),
    ],
)
def test_alt_text_failure_costs_only_the_alt_text(monkeypatch, tmp_path, error):
    """A package the alt-text reader cannot read still converts, and the
    lost alt text counts as a warning."""
    import any2md.converters._office_pictures as pictures
    from any2md.converters import collected_warnings, reset_warnings

    def broken(_z):
        raise error

    monkeypatch.setattr(pictures, "_pptx_alt_texts", broken)
    deck = build_pptx(tmp_path / "deck.pptx", [("a", "b")])
    _fake_docling(monkeypatch, _FakeDoc({1: [_picture(caption="Chart")]}))
    reset_warnings()

    assert office.convert_office(deck, tmp_path / "out", "pptx", force=True)

    got = collected_warnings()
    reset_warnings()
    assert "*Figure: Chart*" in _body(tmp_path / "out" / "deck.md")
    assert any("alt text" in w for w in got)


@pytest.mark.parametrize(
    ("hint", "name", "expected"),
    [
        ("Board Update", "x.pptx", "Board Update"),
        ("PowerPoint Presentation", "q3_review.pptx", "q3 review"),
        ("  ", "a.xlsx", "a"),
        (None, "line\nbreak.xlsx", "line break"),
    ],
)
def test_document_title(hint, name, expected):
    assert office._document_title(hint, name) == expected


# ---- safe-open sourcing through the CLI --------------------------------


def _run_cli(monkeypatch, argv):
    from any2md import cli

    monkeypatch.setattr(sys, "argv", ["any2md", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return exc.value.code


def test_scanned_files_reach_docling_through_descriptors(monkeypatch, tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    build_pptx(corpus / "deck.pptx", [("Title", "Body")])
    build_xlsx(corpus / "book.xlsx", {"S": [["a"]]})
    seen = _fake_docling(monkeypatch, _FakeDoc({1: "# Title\n\nBody"}, ["S"]))

    code = _run_cli(monkeypatch, [str(corpus), "-o", str(tmp_path / "out")])

    assert code == 0
    assert sorted(s.name for s in seen) == ["book.xlsx", "deck.pptx"]
    # Descriptor-backed: opened once with no link followed, never
    # reopened by name, and closed by the CLI after the conversion.
    assert all(s.path is None and s.data is None for s in seen)
    assert all(s.closed for s in seen)


def test_named_file_reaches_docling_as_path(monkeypatch, tmp_path):
    deck = build_pptx(tmp_path / "deck.pptx", [("Title", "Body")])
    seen = _fake_docling(monkeypatch, _FakeDoc({1: "# Title\n\nBody"}))

    code = _run_cli(monkeypatch, [str(deck), "-o", str(tmp_path / "out")])

    assert code == 0
    assert [s.path for s in seen] == [deck]


def test_scanned_file_over_size_cap_is_skipped(monkeypatch, tmp_path, capsys):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    build_xlsx(corpus / "big.xlsx", {"S": [["x" * 4000]]})
    seen = _fake_docling(monkeypatch, _FakeDoc({1: "t"}, ["S"]))

    code = _run_cli(
        monkeypatch,
        [str(corpus), "-o", str(tmp_path / "out"), "--max-file-size", "100"],
    )

    assert code == 0
    assert seen == []
    assert "SKIP (too large)" in capsys.readouterr().err


# ---- Docling warnings count toward --strict ----------------------------


def _docling_that_logs(monkeypatch, logger_name, message, doc):
    import logging

    def fake_convert(src, fmt, capture=None):
        logging.getLogger(logger_name).warning(message)
        logging.getLogger(logger_name).info("below WARNING, not counted")
        return doc

    monkeypatch.setattr(office, "has_docling", lambda: True)
    monkeypatch.setattr(office, "_convert_via_docling", fake_convert)


@pytest.mark.parametrize(
    ("fmt", "logger_name"),
    [
        ("pptx", "docling.backend.mspowerpoint_backend"),
        ("xlsx", "docling.backend.msexcel_backend"),
    ],
)
def test_backend_warnings_reach_the_run_bucket(
    monkeypatch, tmp_path, capsys, fmt, logger_name
):
    from any2md.converters import collected_warnings, reset_warnings

    if fmt == "pptx":
        src = build_pptx(tmp_path / "in.pptx", [("T", "B")])
    else:
        src = build_xlsx(tmp_path / "in.xlsx", {"S": [["a"]]})
    _docling_that_logs(
        monkeypatch,
        logger_name,
        "Could not extract chart data: \x1b[31mboom",
        _FakeDoc({1: "# T\n\nB"}, ["S"]),
    )
    reset_warnings()

    assert office.convert_office(src, tmp_path / "out", fmt, force=True)

    got = collected_warnings()
    reset_warnings()
    assert got == [f"{logger_name}: Could not extract chart data: [31mboom"]
    assert "1 warning(s)" in capsys.readouterr().out


_DOCLING_FILE = "/venv/lib/python3.12/site-packages/docling_core/types/doc/document.py"
_TORCH_FILE = "/venv/lib/python3.12/site-packages/torch/nn/modules/module.py"


def _warn_from(filename, message):
    """Raise a UserWarning as if from ``filename``."""
    import warnings

    module = "docling_core.types" if "docling" in filename else "torch.nn"
    warnings.warn_explicit(message, UserWarning, filename, 1, module=module)


def _docling_that_warns(monkeypatch, doc, during_render=False):
    """Raise a docling-core style Python warning in convert or in export.

    The fake converter enters the capture the way ``_convert_via_docling``
    does, and also raises a torch warning, which must not be counted.
    """
    message = "Provenance bbox coordinate t on page 1 is outside page bounds"

    def fake_convert(src, fmt, capture=None):
        with capture:
            _warn_from(_TORCH_FILE, "weights loaded in float16")
            if not during_render:
                _warn_from(_DOCLING_FILE, message)
        return doc

    if during_render:
        plain_export = doc.export_to_markdown

        def warning_export(**kwargs):
            _warn_from(_DOCLING_FILE, message)
            return plain_export(**kwargs)

        doc.export_to_markdown = warning_export

    monkeypatch.setattr(office, "has_docling", lambda: True)
    monkeypatch.setattr(office, "_convert_via_docling", fake_convert)
    return message


@pytest.mark.parametrize("during_render", [False, True])
def test_python_warnings_are_counted_not_printed(
    monkeypatch, tmp_path, capsys, during_render
):
    from any2md.converters import collected_warnings, reset_warnings

    deck = build_pptx(tmp_path / "deck.pptx", [("T", "B")])
    message = _docling_that_warns(monkeypatch, _FakeDoc({1: "B"}), during_render)
    reset_warnings()

    assert office.convert_office(deck, tmp_path / "out", "pptx", force=True)

    got = collected_warnings()
    reset_warnings()
    assert f"UserWarning: {message}" in got
    # The torch warning is not a document problem.
    assert not any("float16" in w for w in got)
    captured = capsys.readouterr()
    assert "outside page bounds" not in captured.err
    assert "warning(s)" in captured.out


def test_converter_is_built_outside_the_warning_capture(monkeypatch, tmp_path):
    """Model loading or converter construction warnings never count."""
    import any2md._docling_cache as cache_mod
    from any2md.converters import collected_warnings, reset_warnings

    class Converter:
        def convert(self, source):
            return SimpleNamespace(document=_FakeDoc({1: "Body"}))

    def build(fmt):
        _warn_from(_DOCLING_FILE, "raised while building the converter")
        return Converter()

    monkeypatch.setattr(office, "has_docling", lambda: True)
    monkeypatch.setattr(cache_mod, "get_office_converter", build)
    deck = build_pptx(tmp_path / "deck.pptx", [("T", "B")])
    reset_warnings()

    assert office.convert_office(deck, tmp_path / "out", "pptx", force=True)

    got = collected_warnings()
    reset_warnings()
    assert not any("building the converter" in w for w in got)


def test_strict_exits_3_on_python_warning(monkeypatch, tmp_path):
    deck = build_pptx(tmp_path / "deck.pptx", [("T", "B")])
    _docling_that_warns(monkeypatch, _FakeDoc({1: "B"}))

    code = _run_cli(monkeypatch, ["--strict", str(deck), "-o", str(tmp_path / "o")])

    assert code == 3


def test_strict_exits_3_on_docling_warning(monkeypatch, tmp_path):
    deck = build_pptx(tmp_path / "deck.pptx", [("T", "B")])
    _docling_that_logs(
        monkeypatch,
        "docling.backend.mspowerpoint_backend",
        "Could not read the plots of a chart",
        _FakeDoc({1: "# T\n\nB"}),
    )

    code = _run_cli(monkeypatch, ["--strict", str(deck), "-o", str(tmp_path / "o")])

    assert code == 3


# ---- one clear stderr line per failed file -----------------------------


def test_docling_log_line_does_not_reach_stderr(monkeypatch, tmp_path, capsys):
    """Docling's own 'Input document ... is not valid.' stays off stderr.

    With no logging configured, Python prints unhandled WARNING records
    through ``logging.lastResort``. pytest installs root handlers, which
    would hide that path, so the test removes them first.
    """
    import logging

    monkeypatch.setattr(logging.root, "handlers", [])

    def failing_convert(src, fmt, capture=None):
        logging.getLogger("docling.document_converter").warning(
            "Input document %s is not valid.", src.name
        )
        raise RuntimeError("Conversion failed for: book.xlsx with status: failure")

    monkeypatch.setattr(office, "has_docling", lambda: True)
    monkeypatch.setattr(office, "_convert_via_docling", failing_convert)
    book = build_xlsx(tmp_path / "book.xlsx", {"S": [["a"]]})

    assert office.convert_office(book, tmp_path / "out", "xlsx", force=True) is False

    err = capsys.readouterr().err
    assert "is not valid" not in err
    assert err.splitlines() == [
        "  FAIL: book.xlsx -- Docling could not convert this XLSX file: "
        "Conversion failed for: book.xlsx with status: failure"
    ]


def test_docling_logs_still_reach_configured_handlers(monkeypatch, tmp_path):
    """A library caller with its own logging setup still sees the record."""
    import logging

    seen = []

    class Keep(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    monkeypatch.setattr(logging.root, "handlers", [Keep()])

    def failing_convert(src, fmt, capture=None):
        logging.getLogger("docling.document_converter").warning("not valid")
        raise RuntimeError("boom")

    monkeypatch.setattr(office, "has_docling", lambda: True)
    monkeypatch.setattr(office, "_convert_via_docling", failing_convert)
    book = build_xlsx(tmp_path / "book.xlsx", {"S": [["a"]]})

    assert office.convert_office(book, tmp_path / "out", "xlsx", force=True) is False
    assert seen == ["not valid"]
