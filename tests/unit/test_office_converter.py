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

import pytest

import any2md._docling_cache as docling_cache
import any2md.converters.office as office
from any2md._docling import INSTALL_CMD
from any2md._safe_open import SourceFile
from any2md.converters import SUPPORTED_EXTENSIONS, convert_file
from any2md.pipeline import PipelineOptions
from tests._office_fixtures import build_pptx, build_xlsx


class _FakeDoc:
    """The slice of DoclingDocument that ``office`` reads.

    ``pages`` maps page number to Markdown. Every item carries a
    provenance entry for its page unless listed in ``orphans``.
    """

    def __init__(self, pages, sheet_names=(), orphans=0, page_filter=True):
        self._md = dict(pages)
        self.pages = {n: object() for n in self._md}
        self.groups = [
            SimpleNamespace(name=n, label=SimpleNamespace(value="sheet"))
            for n in sheet_names
        ]
        self._items = [
            (SimpleNamespace(prov=[SimpleNamespace(page_no=n)]), 1) for n in self._md
        ] + [(SimpleNamespace(prov=[]), 1)] * orphans
        self._page_filter = page_filter

    def iterate_items(self):
        return iter(self._items)

    def export_to_markdown(self, **kwargs):
        if "page_no" in kwargs:
            if not self._page_filter:
                raise TypeError("unexpected keyword argument 'page_no'")
            return self._md[kwargs["page_no"]]
        return "\n\n".join(self._md.values())


def _fake_docling(monkeypatch, doc):
    """Make ``office`` believe Docling is installed and returns ``doc``."""
    seen: list[SourceFile] = []

    def fake_convert(src, fmt):
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

    def boom(src, fmt):
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
            1: "# Kickoff\n\nWelcome.",
            2: "Body with no title placeholder.",
            3: "# Results\n\n## Detail\n\nUp 12 percent.",
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
    assert office._page_sections(doc, "pptx") is None
    md = office._render_markdown(doc, "pptx", "Deck")
    assert md.startswith("# Deck\n\n# One")
    assert "# Two" in md


def test_sheet_count_mismatch_falls_back():
    doc = _FakeDoc({1: "t1", 2: "t2"}, sheet_names=["only one"])
    assert office._page_sections(doc, "xlsx") is None


def test_docling_core_without_page_filter_falls_back():
    doc = _FakeDoc({1: "t1"}, sheet_names=["S"], page_filter=False)
    assert office._page_sections(doc, "xlsx") is None
    assert "t1" in office._render_markdown(doc, "xlsx", "Book")


def test_demote_headings_skips_code_fences():
    md = "# Title\n\n```\n# not a heading\n```\n\n###### Deep"
    assert office._demote_headings(md, 1) == (
        "## Title\n\n```\n# not a heading\n```\n\n###### Deep"
    )


def test_untitled_slide_nests_its_content_under_slide_n():
    doc = _FakeDoc({1: "#hashtag is body text\n\n# Late title"})
    md = office._render_markdown(doc, "pptx", "Deck")
    assert md == ("# Deck\n\n## Slide 1\n\n#hashtag is body text\n\n### Late title\n")


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


def test_scanned_files_reach_docling_as_bytes(monkeypatch, tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    build_pptx(corpus / "deck.pptx", [("Title", "Body")])
    build_xlsx(corpus / "book.xlsx", {"S": [["a"]]})
    seen = _fake_docling(monkeypatch, _FakeDoc({1: "# Title\n\nBody"}, ["S"]))

    code = _run_cli(monkeypatch, [str(corpus), "-o", str(tmp_path / "out")])

    assert code == 0
    assert sorted(s.name for s in seen) == ["book.xlsx", "deck.pptx"]
    # Bytes-backed: read once through a no-follow descriptor, never
    # reopened by name.
    assert all(s.path is None and s.data for s in seen)


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

    def fake_convert(src, fmt):
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

    def failing_convert(src, fmt):
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

    def failing_convert(src, fmt):
        logging.getLogger("docling.document_converter").warning("not valid")
        raise RuntimeError("boom")

    monkeypatch.setattr(office, "has_docling", lambda: True)
    monkeypatch.setattr(office, "_convert_via_docling", failing_convert)
    book = build_xlsx(tmp_path / "book.xlsx", {"S": [["a"]]})

    assert office.convert_office(book, tmp_path / "out", "xlsx", force=True) is False
    assert seen == ["not valid"]
