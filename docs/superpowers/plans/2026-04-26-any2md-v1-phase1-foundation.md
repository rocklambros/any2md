# any2md v1.0 — Phase 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure any2md into the v1.0 architecture (centralized frontmatter + pipeline + SourceMeta) and rewire all 4 existing converters through it without changing extraction backends. End state: every output file carries SAGE-compatible frontmatter with deterministic `content_hash`, body is NFC-normalized + LF-ended, and a `1.0.0a1` prerelease lands on TestPyPI.

**Architecture:** Two-lane post-processing pipeline (structured / text), shared cleanup stages always last, single YAML emitter (`frontmatter.py`). In Phase 1 the structured lane is empty (no Docling yet) and the text lane is empty (T1–T6 land in Phase 3); only the shared cleanup C1–C7 runs.

**Tech Stack:** Python 3.10+, pytest, pytest-snapshot, ruff, hatchling (existing). Adds reportlab to `[dev]` extras for synthetic-fixture generation.

**Reference:** `docs/superpowers/specs/2026-04-26-any2md-v1-design.md` is the source of truth — sections cited inline as `spec §N`.

**Phase 1 boundary:** No Docling, no `--profile` / `--strict` / `--quiet` / `--verbose` / `--meta` / `--auto-id` flags (Phase 4). Existing CLI flags must keep working. The pipeline runner accepts `PipelineOptions` with a hardcoded default profile of `"aggressive"` for now.

---

## File structure

```
any2md/
  __init__.py                    [MODIFY: bump to "1.0.0a1"]
  cli.py                         [MODIFY: route through new pipeline + frontmatter]
  utils.py                       [MODIFY: keep filename helpers, move yaml/cleanup to new homes]
  frontmatter.py                 [NEW: SourceMeta, derive helpers, compose()]
  validators.py                  [NEW: heading hierarchy + content_hash round-trip checks]
  pipeline/
    __init__.py                  [NEW: PipelineOptions, Lane type, run()]
    cleanup.py                   [NEW: C1–C7 stages]
    structured.py                [NEW: empty stage list (Phase 2 fills it)]
    text.py                      [NEW: empty stage list (Phase 3 fills it)]
  converters/
    __init__.py                  [MODIFY: dispatcher passes PipelineOptions through]
    pdf.py                       [MODIFY: returns (md, SourceMeta); pymupdf4llm only]
    docx.py                      [MODIFY: returns (md, SourceMeta); parse docProps/core.xml]
    html.py                      [MODIFY: returns (md, SourceMeta); use bare_extraction + HEAD]
    txt.py                       [MODIFY: returns (md, SourceMeta)]

tests/
  conftest.py                    [NEW: shared fixtures]
  unit/
    pipeline/
      test_cleanup_nfc.py
      test_cleanup_soft_hyphens.py
      test_cleanup_ligatures.py
      test_cleanup_quotes_dashes.py
      test_cleanup_whitespace.py
      test_cleanup_footnote_markers.py
      test_cleanup_validate.py
      test_runner.py
    test_frontmatter_helpers.py
    test_frontmatter_compose.py
    test_content_hash.py
    test_validators.py
  integration/
    test_pdf_pymupdf_fallback.py
    test_docx_mammoth_fallback.py
    test_html_trafilatura.py
    test_txt.py
  cli/
    test_cli_args.py
    test_cli_existing_flags.py
  fixtures/
    make_fixtures.py             [NEW: regenerates synthetic fixtures]
    docs/
      web_page.html              [NEW: ~1KB synthetic]
      ligatures_and_softhyphens.txt  [NEW]
      multi_column.pdf           [NEW: built by make_fixtures.py]
      table_heavy.docx           [NEW: built by make_fixtures.py]
    snapshots/                   [NEW: golden outputs]
      web_page.md
      ligatures_and_softhyphens.md
      multi_column.md
      table_heavy.md

CHANGELOG.md                     [MODIFY: add 1.0.0a1 entry]
pyproject.toml                   [MODIFY: version 1.0.0a1, [dev] extras]
```

**Parallelization map** (a hint for subagent-driven execution; full graph in §"Parallelism" below):

- Tasks 1–2 are setup, sequential.
- Tasks 3–6 (build fixtures) parallel.
- Tasks 7–8 (types) sequential after 1–2.
- Tasks 9–15 (cleanup stages) parallel after 7–8.
- Task 16 (runner) sequential after 9–15.
- Tasks 17–21 (frontmatter helpers) parallel after 7–8.
- Task 22 (compose) sequential after 17–21.
- Task 23 (validators) parallel after 17.
- Tasks 24–27 (converter rewrites) parallel after 16 + 22.
- Task 28 (CLI rewire) sequential after 24–27.
- Tasks 29–32 (integration tests) parallel after 28 + fixtures.
- Tasks 33–37 (snapshots, validation, version, changelog, release) sequential.

---

## Task 1: Add dev extras and version bump prep

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `[project.optional-dependencies]` and bump dynamic version to 1.0.0a1**

Replace the current `[tool.hatch.version]` block contents and add a dev extras section. Read `pyproject.toml` first; modify in place.

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-snapshot>=0.9.0",
    "reportlab>=4.0.0",
    "ruff>=0.6.0",
]
```

- [ ] **Step 2: Bump `any2md/__init__.py` `__version__`**

```python
"""Convert PDF, DOCX, HTML, and TXT files to LLM-optimized Markdown."""

__version__ = "1.0.0a1"
```

- [ ] **Step 3: Verify install**

Run: `pip install -e ".[dev]"`
Expected: succeeds; `pytest --version` works.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml any2md/__init__.py
git commit -m "chore: Bump to 1.0.0a1 and add [dev] extras"
```

---

## Task 2: Create test scaffolding + conftest

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/__init__.py` (empty)
- Create: `tests/unit/__init__.py` (empty)
- Create: `tests/unit/pipeline/__init__.py` (empty)
- Create: `tests/integration/__init__.py` (empty)
- Create: `tests/cli/__init__.py` (empty)
- Create: `tests/fixtures/__init__.py` (empty)

- [ ] **Step 1: Create `tests/conftest.py`**

```python
"""Shared pytest fixtures for any2md."""

from pathlib import Path

import pytest


@pytest.fixture
def fixture_dir() -> Path:
    """Path to tests/fixtures/docs/."""
    return Path(__file__).parent / "fixtures" / "docs"


@pytest.fixture
def snapshot_dir() -> Path:
    """Path to tests/fixtures/snapshots/."""
    return Path(__file__).parent / "fixtures" / "snapshots"


@pytest.fixture
def tmp_output_dir(tmp_path) -> Path:
    """Per-test output directory under pytest tmp_path."""
    out = tmp_path / "output"
    out.mkdir()
    return out
```

- [ ] **Step 2: Create empty `__init__.py` files in each test subdirectory**

```bash
touch tests/__init__.py tests/unit/__init__.py tests/unit/pipeline/__init__.py \
      tests/integration/__init__.py tests/cli/__init__.py tests/fixtures/__init__.py
```

- [ ] **Step 3: Verify pytest discovery works**

Run: `pytest --collect-only`
Expected: pytest collects 0 tests, no import errors.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: Add pytest scaffolding and shared fixtures"
```

---

## Task 3: Synthetic fixture — HTML page

**Files:**
- Create: `tests/fixtures/docs/web_page.html`

- [ ] **Step 1: Write the fixture**

The HTML must include nav/footer/aside boilerplate so the trafilatura post-processing test exercises boilerplate stripping.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Test Article: Markdown Conversion</title>
  <meta name="author" content="Test Author">
  <meta name="keywords" content="markdown, conversion, test">
</head>
<body>
  <header>
    <nav><a href="/home">Home</a> <a href="/about">About</a></nav>
  </header>
  <main>
    <h1>Test Article: Markdown Conversion</h1>
    <p>This article exists to validate the trafilatura extraction path. It contains a paragraph,
    a list, and a small table.</p>
    <h2>Section One</h2>
    <p>First section content. Soft&shy;hyphenation and curly &ldquo;quotes&rdquo; should normalize.</p>
    <ul>
      <li>Bullet alpha</li>
      <li>Bullet beta</li>
    </ul>
    <h2>Section Two</h2>
    <table>
      <thead><tr><th>Key</th><th>Value</th></tr></thead>
      <tbody>
        <tr><td>k1</td><td>v1</td></tr>
        <tr><td>k2</td><td>v2</td></tr>
      </tbody>
    </table>
  </main>
  <aside>Sidebar noise that must be stripped.</aside>
  <footer>Site footer that must be stripped.</footer>
</body>
</html>
```

- [ ] **Step 2: Verify**

Run: `wc -c tests/fixtures/docs/web_page.html`
Expected: < 2 KB.

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/docs/web_page.html
git commit -m "test: Add synthetic HTML fixture"
```

---

## Task 4: Synthetic fixture — TXT with ligatures and soft-hyphens

**Files:**
- Create: `tests/fixtures/docs/ligatures_and_softhyphens.txt`

- [ ] **Step 1: Write the fixture**

The file must contain U+00AD (soft hyphen), U+FB01 (ﬁ ligature), U+FB02 (ﬂ ligature), and a smart quote, so the C1–C4 cleanup stages have something to act on.

Use a small Python script to write it with the exact bytes (avoid copy-paste mangling):

```bash
python - <<'PY'
from pathlib import Path
content = (
    "EFFICIENT FILE FORMAT TEST\n"
    "==========================\n"
    "\n"
    "This file ex­ists to test soft­hyphen stripping.\n"
    "It also has ligﬁatures (ﬁ and ﬂ) and "
    "“smart quotes” that must normalize.\n"
)
Path("tests/fixtures/docs/ligatures_and_softhyphens.txt").write_text(content, encoding="utf-8")
PY
```

- [ ] **Step 2: Verify byte content**

Run: `python -c "import unicodedata as u; t = open('tests/fixtures/docs/ligatures_and_softhyphens.txt').read(); print('soft-hyphen' if '­' in t else 'MISSING'); print('fi-lig' if 'ﬁ' in t else 'MISSING')"`
Expected: prints `soft-hyphen` and `fi-lig`.

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/docs/ligatures_and_softhyphens.txt
git commit -m "test: Add synthetic TXT fixture with ligatures and soft-hyphens"
```

---

## Task 5: Synthetic fixture — multi-column PDF (reportlab)

**Files:**
- Create: `tests/fixtures/make_fixtures.py`
- Create: `tests/fixtures/docs/multi_column.pdf` (generated)

- [ ] **Step 1: Write `make_fixtures.py`**

```python
"""Regenerate synthetic test fixtures.

Run from repo root: python tests/fixtures/make_fixtures.py
Outputs deterministic PDFs and DOCX files into tests/fixtures/docs/.
Committed alongside generator so test runs don't require regeneration.
"""

from pathlib import Path
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


FIXTURES = Path(__file__).parent / "docs"


def build_multi_column_pdf() -> None:
    """Two-column layout, two pages, with a top heading and body text."""
    out = FIXTURES / "multi_column.pdf"
    c = canvas.Canvas(str(out), pagesize=LETTER)
    width, height = LETTER

    # Page 1
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1 * inch, height - 1 * inch, "Multi-Column Test Document")

    body = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
        "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
        "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris."
    )
    c.setFont("Helvetica", 10)
    # Left column
    text_left = c.beginText(1 * inch, height - 1.5 * inch)
    for line in body.split(". "):
        text_left.textLine(line.strip() + ".")
    c.drawText(text_left)
    # Right column
    text_right = c.beginText(4.5 * inch, height - 1.5 * inch)
    for line in body.split(". "):
        text_right.textLine(line.strip() + ".")
    c.drawText(text_right)

    c.showPage()

    # Page 2 — same shape, different content so dedupe doesn't merge them
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1 * inch, height - 1 * inch, "Page 2 Heading")
    c.setFont("Helvetica", 10)
    text_left = c.beginText(1 * inch, height - 1.5 * inch)
    text_left.textLine("Second-page left column content.")
    c.drawText(text_left)
    text_right = c.beginText(4.5 * inch, height - 1.5 * inch)
    text_right.textLine("Second-page right column content.")
    c.drawText(text_right)

    c.save()


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    build_multi_column_pdf()
    print(f"Wrote {FIXTURES / 'multi_column.pdf'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it to produce the PDF**

Run: `python tests/fixtures/make_fixtures.py`
Expected: writes `tests/fixtures/docs/multi_column.pdf`, ~5–8 KB.

- [ ] **Step 3: Verify PDF opens**

Run: `python -c "import pymupdf; print(len(pymupdf.open('tests/fixtures/docs/multi_column.pdf')))"`
Expected: prints `2`.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/make_fixtures.py tests/fixtures/docs/multi_column.pdf
git commit -m "test: Add multi-column PDF fixture and generator"
```

---

## Task 6: Synthetic fixture — table-heavy DOCX

**Files:**
- Modify: `tests/fixtures/make_fixtures.py` (extend with DOCX builder)
- Create: `tests/fixtures/docs/table_heavy.docx` (generated)

- [ ] **Step 1: Extend `make_fixtures.py`**

Add a function that builds a minimal `.docx` zip directly (no `python-docx` dependency — we deliberately avoid it).

```python
import zipfile


_DOCX_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""

_DOCX_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""

_DOCX_CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/"
                   xmlns:dcterms="http://purl.org/dc/terms/">
  <dc:title>Table Heavy Test Document</dc:title>
  <dc:creator>Test Author</dc:creator>
  <cp:keywords>tables, test, fixture</cp:keywords>
  <dcterms:modified xsi:type="dcterms:W3CDTF" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">2026-04-26T00:00:00Z</dcterms:modified>
</cp:coreProperties>
"""

_DOCX_APP = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Company>Test Org</Company>
</Properties>
"""

_DOCX_DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Table Heavy Test Document</w:t></w:r></w:p>
    <w:p><w:r><w:t>Body paragraph before the table.</w:t></w:r></w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Header 1</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Header 2</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Cell B</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
    <w:p><w:r><w:t>Body paragraph after the table.</w:t></w:r></w:p>
  </w:body>
</w:document>
"""


def build_table_heavy_docx() -> None:
    out = FIXTURES / "table_heavy.docx"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _DOCX_CONTENT_TYPES)
        z.writestr("_rels/.rels", _DOCX_RELS)
        z.writestr("docProps/core.xml", _DOCX_CORE)
        z.writestr("docProps/app.xml", _DOCX_APP)
        z.writestr("word/document.xml", _DOCX_DOCUMENT)
```

Update `main()`:

```python
def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    build_multi_column_pdf()
    build_table_heavy_docx()
    print(f"Wrote {FIXTURES / 'multi_column.pdf'}")
    print(f"Wrote {FIXTURES / 'table_heavy.docx'}")
```

- [ ] **Step 2: Run it**

Run: `python tests/fixtures/make_fixtures.py`
Expected: both files written.

- [ ] **Step 3: Verify DOCX is parseable by mammoth**

Run: `python -c "import mammoth; r = mammoth.convert_to_html(open('tests/fixtures/docs/table_heavy.docx', 'rb')); print('OK' if 'Header 1' in r.value else 'FAIL')"`
Expected: prints `OK`.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/make_fixtures.py tests/fixtures/docs/table_heavy.docx
git commit -m "test: Add table-heavy DOCX fixture and generator"
```

---

## Task 7: PipelineOptions and Lane types

**Files:**
- Create: `any2md/pipeline/__init__.py`
- Create: `any2md/pipeline/structured.py` (empty stage list)
- Create: `any2md/pipeline/text.py` (empty stage list)
- Test: `tests/unit/pipeline/test_runner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/pipeline/test_runner.py
"""Tests for pipeline composition and PipelineOptions."""

from any2md.pipeline import PipelineOptions, run


def test_pipeline_options_defaults():
    opts = PipelineOptions()
    assert opts.profile == "aggressive"
    assert opts.ocr_figures is False
    assert opts.save_images is False
    assert opts.strip_links is False
    assert opts.strict is False


def test_pipeline_options_frozen():
    import dataclasses
    opts = PipelineOptions()
    assert dataclasses.is_dataclass(opts)
    # Frozen dataclasses raise on attribute assignment
    import pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        opts.profile = "conservative"  # type: ignore[misc]


def test_run_returns_text_and_warnings_tuple():
    text, warnings = run("hello\n", "text", PipelineOptions())
    assert isinstance(text, str)
    assert isinstance(warnings, list)


def test_run_invalid_lane_raises():
    import pytest
    with pytest.raises(ValueError, match="lane"):
        run("hello", "bogus", PipelineOptions())  # type: ignore[arg-type]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/pipeline/test_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: any2md.pipeline`.

- [ ] **Step 3: Create `any2md/pipeline/structured.py`**

```python
"""Structured-lane pipeline stages.

Phase 1: empty. Phase 2 fills S1–S4 (figure caption lift, table compactor,
citation normalizer, heading hierarchy).
"""

from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from any2md.pipeline import PipelineOptions

Stage = Callable[[str, "PipelineOptions"], str]

STAGES: list[Stage] = []
```

- [ ] **Step 4: Create `any2md/pipeline/text.py`**

```python
"""Text-lane pipeline stages.

Phase 1: empty. Phase 3 fills T1–T6 (line-wrap repair, dehyphenate,
paragraph dedupe, TOC dedupe, header/footer strip, list/code restore).
"""

from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from any2md.pipeline import PipelineOptions

Stage = Callable[[str, "PipelineOptions"], str]

STAGES: list[Stage] = []
```

- [ ] **Step 5: Create `any2md/pipeline/__init__.py`**

```python
"""Post-processing pipeline runner.

See spec §4. Two lanes (structured / text) merge into shared cleanup
which always runs last. Each stage is a pure str -> str function that
must be a no-op on input it does not match.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable, Literal

Lane = Literal["structured", "text"]
Profile = Literal["conservative", "aggressive", "maximum"]


@dataclass(frozen=True)
class PipelineOptions:
    profile: Profile = "aggressive"
    ocr_figures: bool = False
    save_images: bool = False
    strip_links: bool = False
    strict: bool = False


Stage = Callable[[str, PipelineOptions], str]

# Stages may emit warnings via this contextvar; run() collects them.
_WARNINGS: ContextVar[list[str] | None] = ContextVar("_pipeline_warnings", default=None)


def emit_warning(msg: str) -> None:
    """Stage helper to record a non-fatal warning."""
    bucket = _WARNINGS.get()
    if bucket is not None:
        bucket.append(msg)


def run(text: str, lane: Lane, options: PipelineOptions) -> tuple[str, list[str]]:
    """Run lane-specific stages then shared cleanup. Returns (text, warnings)."""
    if lane not in ("structured", "text"):
        raise ValueError(f"unknown lane: {lane!r}")

    from any2md.pipeline import cleanup, structured, text as text_mod

    lane_stages = structured.STAGES if lane == "structured" else text_mod.STAGES

    warnings: list[str] = []
    token = _WARNINGS.set(warnings)
    try:
        for stage in lane_stages:
            text = stage(text, options)
        for stage in cleanup.STAGES:
            text = stage(text, options)
    finally:
        _WARNINGS.reset(token)

    return text, warnings
```

- [ ] **Step 6: Create empty `any2md/pipeline/cleanup.py` for now**

```python
"""Shared cleanup stages (always last). See spec §4.3."""

from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from any2md.pipeline import PipelineOptions

Stage = Callable[[str, "PipelineOptions"], str]

# Filled in by Tasks 9–15.
STAGES: list[Stage] = []
```

- [ ] **Step 7: Run tests to verify pass**

Run: `pytest tests/unit/pipeline/test_runner.py -v`
Expected: 4 PASS.

- [ ] **Step 8: Commit**

```bash
git add any2md/pipeline/ tests/unit/pipeline/test_runner.py
git commit -m "feat(pipeline): Add PipelineOptions, Lane type, and runner skeleton"
```

---

## Task 8: SourceMeta dataclass + frontmatter module skeleton

**Files:**
- Create: `any2md/frontmatter.py`
- Test: `tests/unit/test_frontmatter_helpers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_frontmatter_helpers.py
"""Tests for SourceMeta and frontmatter module skeleton."""

import dataclasses

from any2md.frontmatter import SourceMeta


def test_source_meta_has_required_fields():
    fields = {f.name for f in dataclasses.fields(SourceMeta)}
    expected = {
        "title_hint", "authors", "organization", "date",
        "keywords", "pages", "word_count", "source_file",
        "source_url", "extracted_via", "lane",
    }
    assert expected <= fields, f"missing fields: {expected - fields}"


def test_source_meta_defaults_are_safe():
    meta = SourceMeta(
        title_hint=None, authors=[], organization=None, date=None,
        keywords=[], pages=None, word_count=None,
        source_file="x.txt", source_url=None,
        doc_type="txt", extracted_via="heuristic", lane="text",
    )
    assert meta.lane == "text"
    assert meta.extracted_via == "heuristic"
    assert meta.doc_type == "txt"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_frontmatter_helpers.py -v`
Expected: FAIL with `ModuleNotFoundError: any2md.frontmatter`.

- [ ] **Step 3: Create `any2md/frontmatter.py` skeleton**

```python
"""SAGE-compatible YAML frontmatter emitter.

See spec §3 (frontmatter contract) and §5.0 (SourceMeta dataclass).
This module is the single producer of the YAML block — converters
never touch YAML directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from any2md.pipeline import Lane


@dataclass
class SourceMeta:
    title_hint: str | None
    authors: list[str]
    organization: str | None
    date: str | None              # ISO-8601 YYYY-MM-DD
    keywords: list[str]
    pages: int | None             # PDFs only
    word_count: int | None        # DOCX/HTML/TXT (post-cleanup)
    source_file: str | None
    source_url: str | None
    doc_type: Literal["pdf", "docx", "html", "txt"]   # v0.7-compat extension
    extracted_via: Literal[
        "docling", "pymupdf4llm", "mammoth+markdownify",
        "trafilatura", "trafilatura+bs4_fallback", "heuristic",
    ]
    lane: Lane
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/unit/test_frontmatter_helpers.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add any2md/frontmatter.py tests/unit/test_frontmatter_helpers.py
git commit -m "feat(frontmatter): Add SourceMeta dataclass"
```

---

## Task 9: Cleanup C1 — `nfc_normalize`

**Files:**
- Modify: `any2md/pipeline/cleanup.py`
- Test: `tests/unit/pipeline/test_cleanup_nfc.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/pipeline/test_cleanup_nfc.py
"""Tests for C1 — nfc_normalize."""

import unicodedata

from any2md.pipeline import PipelineOptions
from any2md.pipeline.cleanup import nfc_normalize


def test_nfc_normalize_decomposed_to_composed():
    decomposed = "café"  # "café" in NFD form
    result = nfc_normalize(decomposed, PipelineOptions())
    assert result == "café"
    assert unicodedata.is_normalized("NFC", result)


def test_nfc_normalize_already_composed_is_noop():
    text = "already café"
    assert nfc_normalize(text, PipelineOptions()) == text


def test_nfc_normalize_empty_is_noop():
    assert nfc_normalize("", PipelineOptions()) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/pipeline/test_cleanup_nfc.py -v`
Expected: FAIL with `ImportError: cannot import name 'nfc_normalize'`.

- [ ] **Step 3: Add the stage**

Replace `any2md/pipeline/cleanup.py` contents:

```python
"""Shared cleanup stages (always last). See spec §4.3."""

from __future__ import annotations

import unicodedata
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from any2md.pipeline import PipelineOptions

Stage = Callable[[str, "PipelineOptions"], str]


def nfc_normalize(text: str, _options: "PipelineOptions") -> str:
    """C1: NFC unicode normalization. Required by SAGE §5.1 for content_hash."""
    return unicodedata.normalize("NFC", text)


STAGES: list[Stage] = [
    nfc_normalize,
]
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/unit/pipeline/test_cleanup_nfc.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add any2md/pipeline/cleanup.py tests/unit/pipeline/test_cleanup_nfc.py
git commit -m "feat(pipeline): C1 nfc_normalize"
```

---

## Task 10: Cleanup C2 — `strip_soft_hyphens`

**Files:**
- Modify: `any2md/pipeline/cleanup.py`
- Test: `tests/unit/pipeline/test_cleanup_soft_hyphens.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/pipeline/test_cleanup_soft_hyphens.py
"""Tests for C2 — strip_soft_hyphens."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.cleanup import strip_soft_hyphens


def test_strip_soft_hyphens_removes_u00ad():
    text = "ex­ists soft­hyphen"
    assert strip_soft_hyphens(text, PipelineOptions()) == "exists softhyphen"


def test_strip_soft_hyphens_no_match_is_noop():
    text = "no soft hyphens here"
    assert strip_soft_hyphens(text, PipelineOptions()) == text


def test_strip_soft_hyphens_preserves_regular_hyphens():
    text = "co-pilot integration"
    assert strip_soft_hyphens(text, PipelineOptions()) == text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/pipeline/test_cleanup_soft_hyphens.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Add the stage**

Append to `any2md/pipeline/cleanup.py`:

```python
def strip_soft_hyphens(text: str, _options: "PipelineOptions") -> str:
    """C2: Remove U+00AD soft hyphen. Frequent PDF artifact."""
    return text.replace("­", "")
```

Update `STAGES`:

```python
STAGES: list[Stage] = [
    nfc_normalize,
    strip_soft_hyphens,
]
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/unit/pipeline/test_cleanup_soft_hyphens.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add any2md/pipeline/cleanup.py tests/unit/pipeline/test_cleanup_soft_hyphens.py
git commit -m "feat(pipeline): C2 strip_soft_hyphens"
```

---

## Task 11: Cleanup C3 — `normalize_ligatures`

**Files:**
- Modify: `any2md/pipeline/cleanup.py`
- Test: `tests/unit/pipeline/test_cleanup_ligatures.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/pipeline/test_cleanup_ligatures.py
"""Tests for C3 — normalize_ligatures."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.cleanup import normalize_ligatures


def test_normalize_ligatures_fi():
    assert normalize_ligatures("ﬁne", PipelineOptions()) == "fine"


def test_normalize_ligatures_fl():
    assert normalize_ligatures("ﬂow", PipelineOptions()) == "flow"


def test_normalize_ligatures_ffi_ffl():
    assert normalize_ligatures("ﬃlation ﬄuent", PipelineOptions()) == "ffilation ffluent"


def test_normalize_ligatures_nbsp_to_space():
    assert normalize_ligatures("foo bar", PipelineOptions()) == "foo bar"


def test_normalize_ligatures_preserves_superscripts():
    # NFKC would fold superscript-2 to "2" — we deliberately do not.
    text = "x² + y²"
    assert normalize_ligatures(text, PipelineOptions()) == text


def test_normalize_ligatures_noop_on_clean_text():
    text = "clean ascii text"
    assert normalize_ligatures(text, PipelineOptions()) == text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/pipeline/test_cleanup_ligatures.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Add the stage**

Append to `any2md/pipeline/cleanup.py`:

```python
# Whitelist of presentation-form ligatures and similar single-glyph compounds
# that are safe to expand. NOT a blanket NFKC pass — that would fold
# superscripts, subscripts, and CJK compatibility characters.
_LIGATURE_TABLE = str.maketrans({
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
    " ": " ",   # non-breaking space → regular space
})


def normalize_ligatures(text: str, _options: "PipelineOptions") -> str:
    """C3: Expand whitelisted ligatures and NBSP only.

    Deliberately not a blanket NFKC pass — see spec §4.3 C3.
    """
    return text.translate(_LIGATURE_TABLE)
```

Update `STAGES`:

```python
STAGES: list[Stage] = [
    nfc_normalize,
    strip_soft_hyphens,
    normalize_ligatures,
]
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/unit/pipeline/test_cleanup_ligatures.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add any2md/pipeline/cleanup.py tests/unit/pipeline/test_cleanup_ligatures.py
git commit -m "feat(pipeline): C3 normalize_ligatures (whitelist-driven)"
```

---

## Task 12: Cleanup C4 — `normalize_quotes_dashes`

**Files:**
- Modify: `any2md/pipeline/cleanup.py`
- Test: `tests/unit/pipeline/test_cleanup_quotes_dashes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/pipeline/test_cleanup_quotes_dashes.py
"""Tests for C4 — normalize_quotes_dashes."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.cleanup import normalize_quotes_dashes


def test_smart_quotes_to_straight():
    text = "“hello” he said"
    assert normalize_quotes_dashes(text, PipelineOptions()) == '"hello" he said'


def test_smart_apostrophes_to_straight():
    text = "it’s a test"
    assert normalize_quotes_dashes(text, PipelineOptions()) == "it's a test"


def test_ellipsis_to_three_dots():
    text = "wait… what"
    assert normalize_quotes_dashes(text, PipelineOptions()) == "wait... what"


def test_em_dash_preserved():
    text = "foo — bar"
    assert normalize_quotes_dashes(text, PipelineOptions()) == "foo — bar"


def test_en_dash_preserved():
    text = "1990–2000"
    assert normalize_quotes_dashes(text, PipelineOptions()) == "1990–2000"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/pipeline/test_cleanup_quotes_dashes.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Add the stage**

Append to `any2md/pipeline/cleanup.py`:

```python
_QUOTE_DASH_TABLE = str.maketrans({
    "“": '"',  # left double quote
    "”": '"',  # right double quote
    "‘": "'",  # left single quote
    "’": "'",  # right single quote
    "…": "",    # ellipsis handled separately so we emit "..."
})


def normalize_quotes_dashes(text: str, _options: "PipelineOptions") -> str:
    """C4: Smart quotes → straight; ellipsis → "..."; en/em dashes preserved."""
    text = text.translate(_QUOTE_DASH_TABLE)
    text = text.replace("…", "...")
    # Note: translate above mapped … to "" because str.maketrans cannot
    # map one char to many; we apply the multi-char replacement here.
    return text
```

Wait — re-read: the table maps `…` to empty string, then we run `replace`. The replace operates on `…` which is no longer present. Fix:

Replace the whole stage with:

```python
_QUOTE_TABLE = str.maketrans({
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
})


def normalize_quotes_dashes(text: str, _options: "PipelineOptions") -> str:
    """C4: Smart quotes → straight; ellipsis → "..."; en/em dashes preserved."""
    text = text.translate(_QUOTE_TABLE)
    text = text.replace("…", "...")
    return text
```

Update `STAGES`:

```python
STAGES: list[Stage] = [
    nfc_normalize,
    strip_soft_hyphens,
    normalize_ligatures,
    normalize_quotes_dashes,
]
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/unit/pipeline/test_cleanup_quotes_dashes.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add any2md/pipeline/cleanup.py tests/unit/pipeline/test_cleanup_quotes_dashes.py
git commit -m "feat(pipeline): C4 normalize_quotes_dashes"
```

---

## Task 13: Cleanup C5 — `collapse_whitespace`

**Files:**
- Modify: `any2md/pipeline/cleanup.py`
- Test: `tests/unit/pipeline/test_cleanup_whitespace.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/pipeline/test_cleanup_whitespace.py
"""Tests for C5 — collapse_whitespace."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.cleanup import collapse_whitespace


def test_collapses_runs_of_spaces():
    assert collapse_whitespace("foo    bar", PipelineOptions()) == "foo bar"


def test_collapses_tabs_to_single_space():
    assert collapse_whitespace("foo\t\tbar", PipelineOptions()) == "foo bar"


def test_strips_trailing_whitespace_per_line():
    assert collapse_whitespace("foo  \nbar  \n", PipelineOptions()) == "foo\nbar\n"


def test_collapses_three_plus_blank_lines_to_two():
    text = "alpha\n\n\n\nbeta"
    assert collapse_whitespace(text, PipelineOptions()) == "alpha\n\nbeta"


def test_preserves_single_blank_line():
    text = "alpha\n\nbeta"
    assert collapse_whitespace(text, PipelineOptions()) == "alpha\n\nbeta"


def test_preserves_indentation_inside_code_blocks():
    # Naive collapse would damage indentation. We only collapse runs of
    # whitespace inside a line, but leading whitespace (indent) is preserved
    # by re only matching 2+ spaces with one or more chars on each side.
    # However our spec for C5 collapses inline runs; leading whitespace in
    # code blocks is rare in pipeline input (Docling/markdownify use fenced
    # blocks already). For Phase 1 we collapse runs >= 2 in body text.
    text = "    indented line"
    # Leading runs are NOT collapsed — only inter-word runs.
    assert collapse_whitespace(text, PipelineOptions()) == "    indented line"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/pipeline/test_cleanup_whitespace.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Add the stage**

Append to `any2md/pipeline/cleanup.py`:

```python
import re

_INTERWORD_RUNS_RE = re.compile(r"(?<=\S)[ \t]{2,}(?=\S)")
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def collapse_whitespace(text: str, _options: "PipelineOptions") -> str:
    """C5: Collapse inter-word whitespace; trim trailing per line; cap blanks at 2."""
    text = _INTERWORD_RUNS_RE.sub(" ", text)
    text = _TRAILING_WS_RE.sub("", text)
    text = _BLANK_RUN_RE.sub("\n\n", text)
    return text
```

Update `STAGES`:

```python
STAGES: list[Stage] = [
    nfc_normalize,
    strip_soft_hyphens,
    normalize_ligatures,
    normalize_quotes_dashes,
    collapse_whitespace,
]
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/unit/pipeline/test_cleanup_whitespace.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add any2md/pipeline/cleanup.py tests/unit/pipeline/test_cleanup_whitespace.py
git commit -m "feat(pipeline): C5 collapse_whitespace"
```

---

## Task 14: Cleanup C6 — `strip_footnote_markers` (profile-gated)

**Files:**
- Modify: `any2md/pipeline/cleanup.py`
- Test: `tests/unit/pipeline/test_cleanup_footnote_markers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/pipeline/test_cleanup_footnote_markers.py
"""Tests for C6 — strip_footnote_markers (aggressive profile only)."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.cleanup import strip_footnote_markers


_BODY_WITH_MARKERS = (
    "This is a sentence[^1]. Another sentence with a marker¹.\n"
    "\n"
    "## Footnotes\n"
    "\n"
    "[^1]: First footnote.\n"
    "1. Footnote one numbered style.\n"
)


def test_aggressive_strips_inline_markers_keeps_footnotes_section():
    opts = PipelineOptions(profile="aggressive")
    out = strip_footnote_markers(_BODY_WITH_MARKERS, opts)
    assert "[^1]" not in out.split("## Footnotes")[0]
    assert "[^1]: First footnote." in out
    assert "¹" not in out.split("## Footnotes")[0]


def test_conservative_is_noop():
    opts = PipelineOptions(profile="conservative")
    assert strip_footnote_markers(_BODY_WITH_MARKERS, opts) == _BODY_WITH_MARKERS


def test_no_footnotes_section_is_noop_even_at_aggressive():
    opts = PipelineOptions(profile="aggressive")
    text = "This is a sentence[^1]. Another¹."
    # No "## Footnotes" or similar — keep markers, we have nothing to point to.
    assert strip_footnote_markers(text, opts) == text


def test_maximum_profile_also_strips():
    opts = PipelineOptions(profile="maximum")
    out = strip_footnote_markers(_BODY_WITH_MARKERS, opts)
    assert "[^1]" not in out.split("## Footnotes")[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/pipeline/test_cleanup_footnote_markers.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Add the stage**

Append to `any2md/pipeline/cleanup.py`:

```python
_INLINE_FN_RE = re.compile(
    r"\[\^(?:\d+|[a-zA-Z][a-zA-Z0-9_-]*)\]"     # [^1] [^note] (markdown footnote refs)
    r"|[¹²³⁰-⁹]"        # superscript digits ¹ ² ³ ⁰-⁹
)
_FOOTNOTES_HEADING_RE = re.compile(
    r"^#{1,3}\s+(footnotes?|notes?|references?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def strip_footnote_markers(text: str, options: "PipelineOptions") -> str:
    """C6: Strip inline footnote markers in body; keep footnotes section.

    Aggressive and maximum profiles only. No-op when no recognizable
    footnotes section exists.
    """
    if options.profile not in ("aggressive", "maximum"):
        return text
    m = _FOOTNOTES_HEADING_RE.search(text)
    if not m:
        return text
    body = text[: m.start()]
    tail = text[m.start():]
    body = _INLINE_FN_RE.sub("", body)
    return body + tail
```

Update `STAGES`:

```python
STAGES: list[Stage] = [
    nfc_normalize,
    strip_soft_hyphens,
    normalize_ligatures,
    normalize_quotes_dashes,
    collapse_whitespace,
    strip_footnote_markers,
]
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/unit/pipeline/test_cleanup_footnote_markers.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add any2md/pipeline/cleanup.py tests/unit/pipeline/test_cleanup_footnote_markers.py
git commit -m "feat(pipeline): C6 strip_footnote_markers (aggressive/maximum)"
```

---

## Task 15: Cleanup C7 — `validate` (read-only, emits warnings)

**Files:**
- Modify: `any2md/pipeline/cleanup.py`
- Test: `tests/unit/pipeline/test_cleanup_validate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/pipeline/test_cleanup_validate.py
"""Tests for C7 — validate (read-only)."""

from any2md.pipeline import PipelineOptions, run


def test_validate_emits_warning_on_missing_h1():
    text = "## Section\n\nNo H1 here.\n"
    out, warnings = run(text, "text", PipelineOptions())
    assert out == text or out.endswith("\n")  # cleanup may have touched whitespace
    assert any("H1" in w for w in warnings), f"warnings={warnings}"


def test_validate_emits_warning_on_skipped_heading_level():
    text = "# Title\n\n## Sub\n\n#### Sub-sub-sub (skip H3)\n"
    _, warnings = run(text, "text", PipelineOptions())
    assert any("skip" in w.lower() for w in warnings)


def test_validate_no_warnings_on_clean_doc():
    text = "# Title\n\n## Section\n\nBody content.\n"
    _, warnings = run(text, "text", PipelineOptions())
    assert warnings == []


def test_validate_does_not_mutate_text():
    text = "# Title\n\n## Section\n\nBody.\n"
    out, _ = run(text, "text", PipelineOptions())
    # Cleanup C1-C5 may normalize whitespace, but the body should still match
    # post-strip semantically.
    assert "# Title" in out
    assert "## Section" in out
    assert "Body" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/pipeline/test_cleanup_validate.py -v`
Expected: FAIL — `validate` not registered.

- [ ] **Step 3: Add the stage**

Append to `any2md/pipeline/cleanup.py`:

```python
from any2md.pipeline import emit_warning  # late import to avoid cycle

_HEADING_RE = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)


def validate(text: str, _options: "PipelineOptions") -> str:
    """C7: Read-only sanity checks. Emits warnings via the pipeline contextvar."""
    levels = [len(m.group(1)) for m in _HEADING_RE.finditer(text)]
    h1_count = sum(1 for level in levels if level == 1)
    if h1_count != 1:
        emit_warning(f"validator: H1 count is {h1_count} (expected 1)")
    for prev, curr in zip(levels, levels[1:]):
        if curr > prev + 1:
            emit_warning(
                f"validator: heading level skip h{prev} -> h{curr}"
            )
            break  # one warning is enough
    return text
```

The late `from any2md.pipeline import emit_warning` import is needed because `cleanup.py` is imported by `pipeline/__init__.py` lazily inside `run()` to avoid a circular import. Since `emit_warning` is only called at execution time (not import time), put the import inside the function body:

Replace `validate` with:

```python
def validate(text: str, _options: "PipelineOptions") -> str:
    """C7: Read-only sanity checks. Emits warnings via the pipeline contextvar."""
    from any2md.pipeline import emit_warning

    levels = [len(m.group(1)) for m in _HEADING_RE.finditer(text)]
    h1_count = sum(1 for level in levels if level == 1)
    if h1_count != 1:
        emit_warning(f"validator: H1 count is {h1_count} (expected 1)")
    for prev, curr in zip(levels, levels[1:]):
        if curr > prev + 1:
            emit_warning(f"validator: heading level skip h{prev} -> h{curr}")
            break
    return text
```

Update `STAGES`:

```python
STAGES: list[Stage] = [
    nfc_normalize,
    strip_soft_hyphens,
    normalize_ligatures,
    normalize_quotes_dashes,
    collapse_whitespace,
    strip_footnote_markers,
    validate,
]
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/unit/pipeline/test_cleanup_validate.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Run full pipeline tests**

Run: `pytest tests/unit/pipeline/ -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add any2md/pipeline/cleanup.py tests/unit/pipeline/test_cleanup_validate.py
git commit -m "feat(pipeline): C7 validate (read-only, emits warnings)"
```

---

## Task 16: Frontmatter helper — `compute_content_hash`

**Files:**
- Modify: `any2md/frontmatter.py`
- Test: `tests/unit/test_content_hash.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_content_hash.py
"""Tests for content_hash determinism (SAGE §5.1)."""

from any2md.frontmatter import compute_content_hash


def test_hash_is_64_lowercase_hex():
    h = compute_content_hash("hello\n")
    assert len(h) == 64
    assert h == h.lower()
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_is_lf_normalized():
    crlf = compute_content_hash("a\r\nb\r\n")
    lf = compute_content_hash("a\nb\n")
    assert crlf == lf


def test_hash_is_nfc_normalized():
    decomposed = compute_content_hash("café")
    composed = compute_content_hash("café")
    assert decomposed == composed


def test_hash_differs_on_content_change():
    a = compute_content_hash("alpha")
    b = compute_content_hash("beta")
    assert a != b


def test_hash_stable_across_calls():
    text = "stable content\n"
    assert compute_content_hash(text) == compute_content_hash(text)


def test_known_vector_empty_string():
    # SHA-256 of empty string
    assert compute_content_hash("") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_content_hash.py -v`
Expected: FAIL — `compute_content_hash` undefined.

- [ ] **Step 3: Add helper to `any2md/frontmatter.py`**

```python
import hashlib
import unicodedata


def compute_content_hash(body: str) -> str:
    """SHA-256 of NFC-normalized, LF-line-ended body. SAGE §5.1.

    The body MUST be the post-pipeline output (after C1–C5). This function
    re-applies NFC and LF normalization defensively so callers can pass any
    string and get a stable hash.
    """
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/unit/test_content_hash.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add any2md/frontmatter.py tests/unit/test_content_hash.py
git commit -m "feat(frontmatter): compute_content_hash with NFC + LF normalization"
```

---

## Task 17: Frontmatter helper — `estimate_tokens`

**Files:**
- Modify: `any2md/frontmatter.py`
- Test: `tests/unit/test_frontmatter_helpers.py` (extend)

- [ ] **Step 1: Write the failing test (append to existing file)**

```python
# tests/unit/test_frontmatter_helpers.py — add at bottom

from any2md.frontmatter import estimate_tokens


def test_estimate_tokens_zero_on_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_ceil_chars_over_4():
    # 4 chars -> 1 token, 5 chars -> 2 tokens (ceil)
    assert estimate_tokens("a" * 4) == 1
    assert estimate_tokens("a" * 5) == 2
    assert estimate_tokens("a" * 8) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_frontmatter_helpers.py -v`
Expected: 2 PASS (existing) + 3 FAIL (new).

- [ ] **Step 3: Add helper**

Append to `any2md/frontmatter.py`:

```python
import math


def estimate_tokens(body: str) -> int:
    """Rough token estimate: ceil(chars / 4). Spec §3.2."""
    return math.ceil(len(body) / 4)
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/unit/test_frontmatter_helpers.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add any2md/frontmatter.py tests/unit/test_frontmatter_helpers.py
git commit -m "feat(frontmatter): estimate_tokens"
```

---

## Task 18: Frontmatter helper — `recommend_chunk_level`

**Files:**
- Modify: `any2md/frontmatter.py`
- Test: `tests/unit/test_frontmatter_helpers.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_frontmatter_helpers.py — add at bottom

from any2md.frontmatter import recommend_chunk_level


def test_chunk_level_h2_when_no_h2_sections():
    assert recommend_chunk_level("# Title\n\nbody only\n") == "h2"


def test_chunk_level_h2_when_all_sections_short():
    body = "# Title\n\n## A\n\nshort\n\n## B\n\nshort\n"
    assert recommend_chunk_level(body) == "h2"


def test_chunk_level_h3_when_any_section_exceeds_1500_tokens():
    # 1500 tokens * 4 chars/token = 6000 chars
    big = "x" * 6500
    body = f"# Title\n\n## A\n\n{big}\n\n## B\n\nshort\n"
    assert recommend_chunk_level(body) == "h3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_frontmatter_helpers.py -v`
Expected: 3 new FAIL.

- [ ] **Step 3: Add helper**

Append to `any2md/frontmatter.py`:

```python
import re

_H2_RE = re.compile(r"^##\s+\S.*$", re.MULTILINE)


def recommend_chunk_level(body: str) -> str:
    """Spec §3.2: h3 if any H2 section body > 1500 estimated tokens; else h2."""
    matches = list(_H2_RE.finditer(body))
    if not matches:
        return "h2"
    boundaries = [m.start() for m in matches] + [len(body)]
    for start, end in zip(boundaries, boundaries[1:]):
        section = body[start:end]
        if estimate_tokens(section) > 1500:
            return "h3"
    return "h2"
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/unit/test_frontmatter_helpers.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add any2md/frontmatter.py tests/unit/test_frontmatter_helpers.py
git commit -m "feat(frontmatter): recommend_chunk_level"
```

---

## Task 19: Frontmatter helper — `extract_abstract`

**Files:**
- Modify: `any2md/frontmatter.py`
- Test: `tests/unit/test_frontmatter_helpers.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_frontmatter_helpers.py — add at bottom

from any2md.frontmatter import extract_abstract


def test_abstract_first_paragraph_after_h1():
    body = (
        "# Title\n\n"
        "This is the first paragraph and is reasonably long enough to be "
        "considered an abstract candidate.\n\n"
        "Second paragraph should be ignored.\n"
    )
    abstract = extract_abstract(body)
    assert abstract is not None
    assert "first paragraph" in abstract
    assert "Second paragraph" not in abstract


def test_abstract_skips_short_paragraphs():
    body = (
        "# Title\n\n"
        "short.\n\n"
        "This is a longer paragraph that should be picked because it exceeds "
        "the 80 character minimum threshold for the abstract heuristic.\n"
    )
    abstract = extract_abstract(body)
    assert abstract is not None
    assert "longer paragraph" in abstract


def test_abstract_truncates_at_400_chars_at_sentence_boundary():
    long_para = "Sentence one is here. " * 30  # ~660 chars
    body = f"# Title\n\n{long_para}\n"
    abstract = extract_abstract(body)
    assert abstract is not None
    assert len(abstract) <= 400
    assert abstract.endswith(".")


def test_abstract_returns_none_when_no_paragraph_after_h1():
    body = "# Title\n\n## Section\n\nbody under section.\n"
    # No bare paragraph between H1 and the next heading.
    assert extract_abstract(body) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_frontmatter_helpers.py -v`
Expected: 4 new FAIL.

- [ ] **Step 3: Add helper**

Append to `any2md/frontmatter.py`:

```python
_H1_LINE_RE = re.compile(r"^#\s+\S.*$", re.MULTILINE)
_HEADING_LINE_RE = re.compile(r"^#{1,6}\s+\S")


def extract_abstract(body: str) -> str | None:
    """First non-heading paragraph ≥ 80 chars after H1, capped at 400.

    Returns None if no qualifying paragraph exists. Spec §3.2.
    """
    h1 = _H1_LINE_RE.search(body)
    if not h1:
        return None

    # Walk paragraphs after the H1 (split on blank lines).
    after = body[h1.end():]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", after)]
    for para in paragraphs:
        if not para:
            continue
        if _HEADING_LINE_RE.match(para):
            continue
        if len(para) < 80:
            continue
        # Truncate at last sentence boundary <= 400.
        if len(para) <= 400:
            return para
        head = para[:400]
        last_dot = head.rfind(".")
        if last_dot >= 80:
            return head[: last_dot + 1]
        return head.rstrip() + "..."
    return None
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/unit/test_frontmatter_helpers.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add any2md/frontmatter.py tests/unit/test_frontmatter_helpers.py
git commit -m "feat(frontmatter): extract_abstract heuristic"
```

---

## Task 20: Frontmatter helper — `extract_title`

**Files:**
- Modify: `any2md/frontmatter.py`
- Test: `tests/unit/test_frontmatter_helpers.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_frontmatter_helpers.py — add at bottom

from any2md.frontmatter import derive_title


def test_derive_title_uses_first_h1():
    body = "# My Title\n\nbody\n"
    assert derive_title(body, title_hint=None, fallback="x.pdf") == "My Title"


def test_derive_title_falls_back_to_hint_when_no_h1():
    body = "## No H1\n\nbody\n"
    assert derive_title(body, title_hint="Hint Title", fallback="x.pdf") == "Hint Title"


def test_derive_title_falls_back_to_filename_when_neither():
    body = "no headings here\n"
    assert derive_title(body, title_hint=None, fallback="my_doc.pdf") == "my doc"


def test_derive_title_strips_markdown_emphasis_in_h1():
    body = "# **Bold Title** _emphasis_\n"
    assert derive_title(body, title_hint=None, fallback="x") == "Bold Title emphasis"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_frontmatter_helpers.py -v`
Expected: 4 new FAIL.

- [ ] **Step 3: Add helper**

Append to `any2md/frontmatter.py`:

```python
_FIRST_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_MD_EMPHASIS_RE = re.compile(r"[*_]+")


def derive_title(body: str, title_hint: str | None, fallback: str) -> str:
    """Pick title: first H1, else hint, else cleaned filename stem."""
    m = _FIRST_H1_RE.search(body)
    if m:
        title = _MD_EMPHASIS_RE.sub("", m.group(1)).strip()
        if title:
            return title
    if title_hint:
        return title_hint.strip()
    stem = fallback.rsplit(".", 1)[0]
    return stem.replace("_", " ").strip() or "Untitled"
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/unit/test_frontmatter_helpers.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add any2md/frontmatter.py tests/unit/test_frontmatter_helpers.py
git commit -m "feat(frontmatter): derive_title with H1/hint/filename fallback chain"
```

---

## Task 21: Frontmatter `compose()` — full SAGE-compatible YAML emitter

**Files:**
- Modify: `any2md/frontmatter.py`
- Test: `tests/unit/test_frontmatter_compose.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_frontmatter_compose.py
"""Tests for frontmatter.compose() — SAGE-compatible output."""

from datetime import date

import yaml

from any2md.frontmatter import SourceMeta, compose
from any2md.pipeline import PipelineOptions


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Helper: split a frontmatter+body string into (yaml_dict, body_str).

    compose() emits a blank-line separator after the closing ---, so we
    strip a single leading newline from the body to recover the body that
    was passed into compose().
    """
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    fm = yaml.safe_load(text[4:end])
    body = text[end + 5 :]
    if body.startswith("\n"):
        body = body[1:]
    return fm, body


def _meta(**overrides) -> SourceMeta:
    base = dict(
        title_hint=None, authors=[], organization=None, date=None,
        keywords=[], pages=None, word_count=None,
        source_file="x.txt", source_url=None,
        doc_type="txt", extracted_via="heuristic", lane="text",
    )
    base.update(overrides)
    return SourceMeta(**base)


def test_compose_emits_required_sage_fields():
    body = "# Title\n\nbody\n"
    out = compose(body, _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    for key in [
        "title", "document_id", "version", "date", "status",
        "document_type", "content_domain", "authors", "organization",
        "generation_metadata", "content_hash",
    ]:
        assert key in fm, f"missing required field: {key}"


def test_compose_status_is_draft():
    out = compose("# T\n\nbody\n", _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm["status"] == "draft"


def test_compose_document_type_and_content_domain_are_empty():
    out = compose("# T\n\nbody\n", _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm["document_type"] == ""
    assert fm["content_domain"] == []


def test_compose_document_id_empty_by_default():
    out = compose("# T\n\nbody\n", _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm["document_id"] == ""


def test_compose_authored_by_unknown():
    out = compose("# T\n\nbody\n", _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm["generation_metadata"]["authored_by"] == "unknown"


def test_compose_content_hash_matches_body():
    body = "# T\n\nbody\n"
    out = compose(body, _meta(), PipelineOptions())
    fm, body_out = _split_frontmatter(out)
    from any2md.frontmatter import compute_content_hash
    assert fm["content_hash"] == compute_content_hash(body_out)


def test_compose_includes_source_file_extension_field():
    out = compose("# T\n\nbody\n", _meta(source_file="report.pdf"), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm["source_file"] == "report.pdf"


def test_compose_uses_source_url_when_provided():
    out = compose(
        "# T\n\nbody\n",
        _meta(source_file=None, source_url="https://example.com/article"),
        PipelineOptions(),
    )
    fm, _ = _split_frontmatter(out)
    assert fm["source_url"] == "https://example.com/article"


def test_compose_token_estimate_present_and_positive():
    out = compose("# T\n\n" + "x" * 100 + "\n", _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm["token_estimate"] >= 25


def test_compose_skips_abstract_for_short_doc():
    short = "# T\n\nshort body.\n"
    out = compose(short, _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert "abstract_for_rag" not in fm or fm.get("abstract_for_rag") in (None, "")


def test_compose_includes_abstract_for_long_doc():
    big = "# T\n\n" + "This is a long abstract sentence that should be picked. " * 100 + "\n"
    out = compose(big, _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm.get("abstract_for_rag")
    assert len(fm["abstract_for_rag"]) <= 400


def test_compose_body_ends_with_lf():
    out = compose("# T\n\nbody\n", _meta(), PipelineOptions())
    assert out.endswith("\n")
    assert "\r" not in out


def test_compose_body_is_nfc():
    body = "# T\n\ncafé\n"  # decomposed
    out = compose(body, _meta(), PipelineOptions())
    _, body_out = _split_frontmatter(out)
    assert "café" in body_out
    assert "café" not in body_out


def test_compose_deterministic_for_same_input():
    body = "# Title\n\nstable body content here.\n"
    a = compose(body, _meta(date="2026-04-26"), PipelineOptions())
    b = compose(body, _meta(date="2026-04-26"), PipelineOptions())
    assert a == b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_frontmatter_compose.py -v`
Expected: FAIL — `compose` undefined.

- [ ] **Step 3: Add `compose()` to `any2md/frontmatter.py`**

```python
from datetime import date as _date_cls
from typing import Any

from any2md.pipeline import PipelineOptions


def _yaml_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
             .replace('"', '\\"')
             .replace("\n", "\\n")
             .replace("\r", "\\r")
    )


def _emit_value(value: Any) -> str:
    """Emit a scalar or simple list as YAML (one line)."""
    if value is None:
        return '""'
    if isinstance(value, str):
        return f'"{_yaml_escape(value)}"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    raise TypeError(f"unsupported scalar: {type(value)}")


def _emit_array(values: list[str]) -> str:
    if not values:
        return "[]"
    items = ", ".join(_emit_value(v) for v in values)
    return f"[{items}]"


def compose(body: str, meta: SourceMeta, options: PipelineOptions) -> str:
    """Build a complete SAGE-compatible Markdown document.

    Steps:
    1. Normalize body to NFC + LF endings (matches content_hash invariant).
    2. Derive title, content_hash, token_estimate, chunk_level, abstract.
    3. Emit YAML frontmatter in spec §3.2-3.4 order.
    4. Concatenate frontmatter + body.
    """
    # 1. Normalize body
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    import unicodedata
    body = unicodedata.normalize("NFC", body)
    if not body.endswith("\n"):
        body += "\n"

    # 2. Derive
    fallback = meta.source_file or meta.source_url or "untitled"
    title = derive_title(body, meta.title_hint, fallback)
    content_hash = compute_content_hash(body)
    token_est = estimate_tokens(body)
    chunk_level = recommend_chunk_level(body)
    abstract = extract_abstract(body) if token_est >= 500 else None
    today = _date_cls.today().isoformat()
    fm_date = meta.date or today

    # 3. Emit YAML in SAGE-defined order
    lines: list[str] = ["---"]
    lines.append(f"title: {_emit_value(title)}")
    lines.append('document_id: ""')
    lines.append('version: "1"')
    lines.append(f"date: {_emit_value(fm_date)}")
    lines.append('status: "draft"')
    lines.append('document_type: ""')
    lines.append("content_domain: []")
    lines.append(f"authors: {_emit_array(meta.authors)}")
    lines.append(f"organization: {_emit_value(meta.organization or '')}")
    lines.append("generation_metadata:")
    lines.append('  authored_by: "unknown"')
    lines.append(f'content_hash: "{content_hash}"')
    if meta.keywords:
        lines.append(f"keywords: {_emit_array(meta.keywords)}")
    lines.append(f"token_estimate: {token_est}")
    lines.append(f'recommended_chunk_level: "{chunk_level}"')
    if abstract:
        lines.append(f"abstract_for_rag: {_emit_value(abstract)}")
    # any2md extension fields (preserved from v0.7 for traceability)
    if meta.source_file:
        lines.append(f"source_file: {_emit_value(meta.source_file)}")
    if meta.source_url:
        lines.append(f"source_url: {_emit_value(meta.source_url)}")
    lines.append(f'type: "{meta.doc_type}"')          # v0.7-compat field (spec §3.2)
    lines.append(f'extracted_via: "{meta.extracted_via}"')  # v1.0 provenance extension
    if meta.pages is not None:
        lines.append(f"pages: {meta.pages}")
    if meta.word_count is not None:
        lines.append(f"word_count: {meta.word_count}")
    lines.append("---")
    lines.append("")  # blank line separator

    return "\n".join(lines) + "\n" + body
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/unit/test_frontmatter_compose.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add any2md/frontmatter.py tests/unit/test_frontmatter_compose.py
git commit -m "feat(frontmatter): compose() SAGE-compatible YAML emitter"
```

---

## Task 22: validators.py — heading + content_hash round-trip

**Files:**
- Create: `any2md/validators.py`
- Test: `tests/unit/test_validators.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_validators.py
"""Tests for the validators module."""

import pytest

from any2md.validators import (
    check_content_hash_round_trip,
    check_heading_hierarchy,
)


def test_heading_hierarchy_clean_doc():
    issues = check_heading_hierarchy("# A\n\n## B\n\n### C\n")
    assert issues == []


def test_heading_hierarchy_missing_h1():
    issues = check_heading_hierarchy("## B\n\n### C\n")
    assert any("H1" in i for i in issues)


def test_heading_hierarchy_skip():
    issues = check_heading_hierarchy("# A\n\n#### D\n")
    assert any("skip" in i.lower() for i in issues)


def test_content_hash_round_trip_pass():
    body = "# Title\n\nbody.\n"
    from any2md.frontmatter import compute_content_hash
    expected = compute_content_hash(body)
    assert check_content_hash_round_trip(body, expected) is True


def test_content_hash_round_trip_fail():
    body = "# Title\n\nbody.\n"
    assert check_content_hash_round_trip(body, "deadbeef" * 8) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_validators.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Create `any2md/validators.py`**

```python
"""Optional sanity checks. Used by the CLI to surface warnings."""

from __future__ import annotations

import re

from any2md.frontmatter import compute_content_hash

_HEADING_RE = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)


def check_heading_hierarchy(body: str) -> list[str]:
    """Return a list of human-readable issues. Empty list = clean."""
    issues: list[str] = []
    levels = [len(m.group(1)) for m in _HEADING_RE.finditer(body)]
    if sum(1 for level in levels if level == 1) != 1:
        issues.append("H1 count is not exactly 1")
    for prev, curr in zip(levels, levels[1:]):
        if curr > prev + 1:
            issues.append(f"heading level skip h{prev} -> h{curr}")
            break
    return issues


def check_content_hash_round_trip(body: str, expected: str) -> bool:
    return compute_content_hash(body) == expected
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/unit/test_validators.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add any2md/validators.py tests/unit/test_validators.py
git commit -m "feat(validators): heading hierarchy and content_hash round-trip"
```

---

## Task 23: TXT converter rewrite

**Files:**
- Modify: `any2md/converters/txt.py`
- Test: `tests/integration/test_txt.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/test_txt.py
"""Integration test: TXT converter end-to-end."""

import yaml

from any2md.cli import main
from any2md.pipeline import PipelineOptions


def test_txt_end_to_end_writes_sage_compat_output(fixture_dir, tmp_output_dir, monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["any2md", "-o", str(tmp_output_dir), str(fixture_dir / "ligatures_and_softhyphens.txt")],
    )
    main()
    out_files = list(tmp_output_dir.glob("*.md"))
    assert len(out_files) == 1
    out = out_files[0].read_text(encoding="utf-8")
    # Frontmatter shape
    assert out.startswith("---\n")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    body = out[end + 5:]
    assert fm["status"] == "draft"
    assert fm["extracted_via"] == "heuristic"
    assert fm["source_file"].endswith(".txt")
    assert fm["content_hash"]
    # Cleanup applied
    assert "­" not in body  # soft hyphen stripped
    assert "ﬁ" not in body  # ligature expanded
    assert "“" not in body  # smart quote normalized
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_txt.py -v`
Expected: FAIL — current TXT converter still emits v0.7 frontmatter.

- [ ] **Step 3: Rewrite `any2md/converters/txt.py`**

Replace contents:

```python
"""Plain text to Markdown converter (v1.0)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from any2md import frontmatter as fm_mod
from any2md import pipeline
from any2md.frontmatter import SourceMeta, compose
from any2md.pipeline import PipelineOptions
from any2md.utils import sanitize_filename, read_text_with_fallback

# Existing structurize() heuristic stays in this file from v0.7 — keep it.
# (re-imported below — copy from the old file unchanged)
import re

_SEPARATOR_RE = re.compile(r"^([=\-*_~])\1{2,}\s*$")
_BULLET_RE = re.compile(r"^[•–·]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\(?\d{1,3}[.)]\)?\s+(.*)$")
_LETTERED_RE = re.compile(r"^\(?[a-z][.)]\)?\s+(.*)$")
_INDENT_RE = re.compile(r"^(?:    |\t)(.*)$")
_ALL_CAPS_RE = re.compile(r"^[A-Z][A-Z0-9 /&,:\-]{2,78}$")


def _is_title_case(line: str) -> bool:
    words = line.split()
    if len(words) < 2:
        return False
    skip = {"a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "with", "by", "from", "is"}
    caps = sum(1 for w in words if w[0].isupper() or w.lower() in skip)
    return caps >= len(words) * 0.7


def structurize(text: str) -> str:
    """Convert plain text to Markdown by detecting implicit structure.

    Unchanged from v0.7. Output goes through the v1.0 cleanup pipeline.
    """
    text = text.replace("\t", "    ")
    lines = text.split("\n")
    output: list[str] = []
    i = 0
    title_emitted = False
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()
        prev_stripped = lines[i - 1].strip() if i > 0 else ""
        next_stripped = lines[i + 1].strip() if i < n - 1 else ""

        sep_match = _SEPARATOR_RE.match(stripped)
        if sep_match and stripped:
            char = sep_match.group(1)
            if prev_stripped and output and output[-1].strip():
                prev_text = output[-1].strip()
                if not prev_text.startswith("#"):
                    if char == "=":
                        output[-1] = "# " + prev_text
                    else:
                        output[-1] = "## " + prev_text
                    i += 1
                    continue
            output.append("---")
            i += 1
            continue

        if _INDENT_RE.match(line) and stripped:
            block_lines: list[str] = []
            while i < n and (_INDENT_RE.match(lines[i]) or not lines[i].strip()):
                if not lines[i].strip():
                    j = i + 1
                    while j < n and not lines[j].strip():
                        j += 1
                    if j < n and _INDENT_RE.match(lines[j]):
                        block_lines.append("")
                        i += 1
                        continue
                    else:
                        break
                indent_m = _INDENT_RE.match(lines[i])
                block_lines.append(indent_m.group(1) if indent_m else lines[i])
                i += 1
            output.append("```")
            output.extend(block_lines)
            output.append("```")
            continue

        bullet_m = _BULLET_RE.match(stripped)
        if bullet_m:
            output.append("- " + bullet_m.group(1))
            i += 1
            continue

        num_m = _NUMBERED_RE.match(stripped)
        let_m = _LETTERED_RE.match(stripped) if not num_m else None
        if num_m:
            output.append("1. " + num_m.group(1))
            i += 1
            continue
        if let_m:
            output.append("1. " + let_m.group(1))
            i += 1
            continue

        if _ALL_CAPS_RE.match(stripped) and len(stripped) <= 80:
            if not next_stripped or i == n - 1:
                if not title_emitted:
                    output.append("# " + stripped.title())
                    title_emitted = True
                else:
                    output.append("## " + stripped.title())
                i += 1
                continue

        if (
            3 <= len(stripped) <= 80
            and not prev_stripped
            and not next_stripped
            and _is_title_case(stripped)
            and not stripped.endswith((".", "!", "?", ",", ";", ":"))
            and i > 0
        ):
            output.append("### " + stripped)
            i += 1
            continue

        output.append(line)
        i += 1

    return "\n".join(output)


def _build_meta(txt_path: Path, body: str) -> SourceMeta:
    return SourceMeta(
        title_hint=None,
        authors=[],
        organization=None,
        date=date.fromtimestamp(txt_path.stat().st_mtime).isoformat()
            if txt_path.exists() else None,
        keywords=[],
        pages=None,
        word_count=len(body.split()),
        source_file=txt_path.name,
        source_url=None,
        doc_type="txt",
        extracted_via="heuristic",
        lane="text",
    )


def convert_txt(
    txt_path: Path,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
    strip_links_flag: bool = False,
) -> bool:
    """Convert a plain-text file to v1.0 SAGE-compatible Markdown."""
    if options is None:
        options = PipelineOptions(strip_links=strip_links_flag)

    out_name = sanitize_filename(txt_path.name)
    out_path = output_dir / out_name
    if out_path.exists() and not force:
        print(f"  SKIP (exists): {out_name}")
        return True

    try:
        raw_text = read_text_with_fallback(txt_path)
        if not raw_text.strip():
            print(f"  FAIL: {txt_path.name} -- empty file", file=sys.stderr)
            return False

        md_text = structurize(raw_text)
        md_text, warnings = pipeline.run(md_text, "text", options)
        meta = _build_meta(txt_path, md_text)
        full = compose(md_text, meta, options)

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(full, encoding="utf-8", newline="\n")
        word_count = meta.word_count or 0
        suffix = f", {len(warnings)} warning(s)" if warnings else ""
        print(f"  OK: {out_name} ({word_count} words{suffix})")
        return True

    except (OSError, ValueError) as e:
        print(f"  FAIL: {txt_path.name} -- {e}", file=sys.stderr)
        return False
```

- [ ] **Step 4: Update `any2md/converters/__init__.py` so it forwards `options`**

Replace contents:

```python
"""Converter dispatcher for any2md."""

import sys
from pathlib import Path

from any2md.pipeline import PipelineOptions

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".txt"}


def convert_file(
    file_path: Path,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
    strip_links_flag: bool = False,
) -> bool:
    if options is None:
        options = PipelineOptions(strip_links=strip_links_flag)
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        from any2md.converters.pdf import convert_pdf
        return convert_pdf(file_path, output_dir, options=options, force=force)
    if ext == ".docx":
        from any2md.converters.docx import convert_docx
        return convert_docx(file_path, output_dir, options=options, force=force)
    if ext in (".html", ".htm"):
        from any2md.converters.html import convert_html
        return convert_html(file_path, output_dir, options=options, force=force)
    if ext == ".txt":
        from any2md.converters.txt import convert_txt
        return convert_txt(file_path, output_dir, options=options, force=force)
    print(f"  UNSUPPORTED: {file_path.name} (no converter for {ext})", file=sys.stderr)
    return False
```

- [ ] **Step 5: Run test (will fail because cli.py still uses v0.7 wiring; that's Task 27)**

Run: `pytest tests/integration/test_txt.py -v`
Expected: FAIL — but failure now is in CLI wiring, which Task 27 will fix.

To verify TXT converter works in isolation:

```python
python - <<'PY'
from pathlib import Path
from any2md.converters.txt import convert_txt
from any2md.pipeline import PipelineOptions
out = Path("/tmp/any2md_test_txt"); out.mkdir(exist_ok=True)
ok = convert_txt(
    Path("tests/fixtures/docs/ligatures_and_softhyphens.txt"),
    out,
    options=PipelineOptions(),
    force=True,
)
print("OK" if ok else "FAIL")
print((out / "ligatures_and_softhyphens.md").read_text()[:200])
PY
```

Expected: prints `OK` and shows YAML frontmatter starting with `---\ntitle:`.

- [ ] **Step 6: Commit**

```bash
git add any2md/converters/txt.py any2md/converters/__init__.py
git commit -m "feat(converters): TXT converter on v1.0 pipeline"
```

---

## Task 24: HTML converter rewrite

**Files:**
- Modify: `any2md/converters/html.py`
- Test: `tests/integration/test_html_trafilatura.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/test_html_trafilatura.py
"""Integration test: HTML converter end-to-end."""

import yaml

from any2md.converters.html import convert_html
from any2md.pipeline import PipelineOptions


def test_html_local_file_emits_v1_frontmatter(fixture_dir, tmp_output_dir):
    ok = convert_html(
        fixture_dir / "web_page.html",
        tmp_output_dir,
        options=PipelineOptions(),
        force=True,
    )
    assert ok
    out_files = list(tmp_output_dir.glob("*.md"))
    assert len(out_files) == 1
    out = out_files[0].read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    body = out[end + 5:]
    assert fm["status"] == "draft"
    assert "trafilatura" in fm["extracted_via"]
    # boilerplate stripped
    assert "Sidebar noise" not in body
    assert "Site footer" not in body
    # body content present
    assert "Test Article" in fm["title"] or "Test Article" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_html_trafilatura.py -v`
Expected: FAIL — `convert_html` signature still v0.7.

- [ ] **Step 3: Rewrite `any2md/converters/html.py`**

Keep the existing SSRF protection and `fetch_url` logic; replace the convert function.

```python
"""HTML to Markdown converter (v1.0)."""

from __future__ import annotations

import ipaddress
import socket
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import trafilatura
import markdownify
from bs4 import BeautifulSoup

from any2md import pipeline
from any2md.frontmatter import SourceMeta, compose
from any2md.pipeline import PipelineOptions
from any2md.utils import (
    sanitize_filename, url_to_filename, read_text_with_fallback,
)

_MAX_FILE_SIZE = 100 * 1024 * 1024


def _validate_url_host(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return f"No hostname in URL: {url}"
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return f"Cannot resolve hostname: {hostname}"
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (addr.is_private or addr.is_reserved
                or addr.is_loopback or addr.is_link_local):
            return f"URL resolves to disallowed address: {ip_str}"
    return None


def fetch_url(url: str) -> tuple[str | None, str | None]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None, f"Unsupported URL scheme: {parsed.scheme!r}"
    err = _validate_url_host(url)
    if err:
        return None, err
    try:
        html = trafilatura.fetch_url(url)
        if html is None:
            return None, f"Failed to fetch URL: {url}"
        return html, None
    except Exception as e:  # noqa: BLE001
        return None, f"Error fetching URL: {e}"


def _http_last_modified(url: str) -> str | None:
    """Single HEAD request for Last-Modified. Best-effort."""
    try:
        req = urllib.request.Request(
            url, method="HEAD",
            headers={"User-Agent": "any2md/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            lm = resp.headers.get("Last-Modified")
            if lm:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(lm).date().isoformat()
    except Exception:  # noqa: BLE001
        pass
    return None


def _bs4_preclean(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(
        ["script", "style", "nav", "header", "footer", "aside", "iframe"]
    ):
        tag.decompose()
    return str(soup)


def _extract(raw_html: str) -> tuple[str, str]:
    """Returns (markdown, extracted_via)."""
    md = trafilatura.extract(
        raw_html, output_format="markdown",
        include_formatting=True, include_links=True,
    )
    if md:
        return md, "trafilatura"
    cleaned = _bs4_preclean(raw_html)
    md = markdownify.markdownify(cleaned, heading_style="ATX", strip=["img"])
    return md, "trafilatura+bs4_fallback"


def _extract_metadata(raw_html: str) -> tuple[str | None, list[str], str | None, str | None, list[str]]:
    """Returns (title_hint, authors, organization, date, keywords)."""
    try:
        bare = trafilatura.bare_extraction(
            raw_html, with_metadata=True, output_format="python"
        )
    except Exception:  # noqa: BLE001
        return None, [], None, None, []
    if not bare:
        return None, [], None, None, []
    title = bare.get("title")
    authors_raw = bare.get("author") or ""
    authors = [a.strip() for a in authors_raw.split(",") if a.strip()]
    org = bare.get("sitename")
    d = bare.get("date")
    kw = bare.get("categories") or []
    return title, authors, org, d, list(kw)


def convert_html(
    html_path: Path | None,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
    strip_links_flag: bool = False,
    source_url: str | None = None,
    html_content: str | None = None,
) -> bool:
    if options is None:
        options = PipelineOptions(strip_links=strip_links_flag)

    if source_url:
        out_name = url_to_filename(source_url)
        name_for_error = source_url
    elif html_path is not None:
        out_name = sanitize_filename(html_path.name)
        name_for_error = html_path.name
    else:
        print("  FAIL: source_url or html_path required", file=sys.stderr)
        return False

    out_path = output_dir / out_name
    if out_path.exists() and not force:
        print(f"  SKIP (exists): {out_name}")
        return True

    try:
        if html_content is not None:
            raw_html = html_content
        elif html_path is not None:
            file_size = html_path.stat().st_size
            if file_size > _MAX_FILE_SIZE:
                print(
                    f"  FAIL: {name_for_error} -- file too large "
                    f"({file_size} bytes, max {_MAX_FILE_SIZE})",
                    file=sys.stderr,
                )
                return False
            raw_html = read_text_with_fallback(html_path)
        else:
            print("  FAIL: html_content or html_path required", file=sys.stderr)
            return False

        md_text, extracted_via = _extract(raw_html)
        title_hint, authors, org, doc_date, keywords = _extract_metadata(raw_html)

        if source_url and not doc_date:
            doc_date = _http_last_modified(source_url)
        if not doc_date:
            doc_date = date.today().isoformat()

        md_text, warnings = pipeline.run(md_text, "text", options)

        meta = SourceMeta(
            title_hint=title_hint,
            authors=authors,
            organization=org,
            date=doc_date,
            keywords=keywords,
            pages=None,
            word_count=len(md_text.split()),
            source_file=html_path.name if html_path else None,
            source_url=source_url,
            doc_type="html",
            extracted_via=extracted_via,
            lane="text",
        )
        full = compose(md_text, meta, options)

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(full, encoding="utf-8", newline="\n")
        wc = meta.word_count or 0
        suffix = f", {len(warnings)} warning(s)" if warnings else ""
        print(f"  OK: {out_name} ({wc} words{suffix})")
        return True

    except (OSError, ValueError, TypeError) as e:
        print(f"  FAIL: {name_for_error} -- {e}", file=sys.stderr)
        return False


def convert_url(
    url: str,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
    strip_links_flag: bool = False,
) -> bool:
    html_content, err = fetch_url(url)
    if err:
        print(f"  FAIL: {url} -- {err}", file=sys.stderr)
        return False
    return convert_html(
        None, output_dir, options=options, force=force,
        strip_links_flag=strip_links_flag,
        source_url=url, html_content=html_content,
    )
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/integration/test_html_trafilatura.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add any2md/converters/html.py tests/integration/test_html_trafilatura.py
git commit -m "feat(converters): HTML converter on v1.0 pipeline + bare_extraction metadata"
```

---

## Task 25: DOCX converter rewrite

**Files:**
- Modify: `any2md/converters/docx.py`
- Test: `tests/integration/test_docx_mammoth_fallback.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_docx_mammoth_fallback.py
"""Integration test: DOCX converter (mammoth fallback path)."""

import yaml

from any2md.converters.docx import convert_docx
from any2md.pipeline import PipelineOptions


def test_docx_emits_v1_frontmatter_with_core_props(fixture_dir, tmp_output_dir):
    ok = convert_docx(
        fixture_dir / "table_heavy.docx",
        tmp_output_dir,
        options=PipelineOptions(),
        force=True,
    )
    assert ok
    out_files = list(tmp_output_dir.glob("*.md"))
    assert len(out_files) == 1
    out = out_files[0].read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    body = out[end + 5:]
    assert fm["title"] == "Table Heavy Test Document"
    assert fm["authors"] == ["Test Author"]
    assert fm["organization"] == "Test Org"
    assert fm["date"] == "2026-04-26"
    assert "tables" in fm.get("keywords", [])
    assert fm["extracted_via"] == "mammoth+markdownify"
    assert fm["status"] == "draft"
    # Body has table content
    assert "Header 1" in body and "Cell A" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_docx_mammoth_fallback.py -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite `any2md/converters/docx.py`**

```python
"""DOCX to Markdown converter (v1.0). Mammoth fallback path only in Phase 1."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from pathlib import Path

import mammoth
import markdownify

from any2md import pipeline
from any2md.frontmatter import SourceMeta, compose
from any2md.pipeline import PipelineOptions
from any2md.utils import sanitize_filename

_NS_CORE = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dcterms": "http://purl.org/dc/terms/",
}
_NS_APP = {"ext": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"}


def _read_docx_metadata(docx_path: Path) -> dict[str, object]:
    out: dict[str, object] = {
        "title_hint": None, "authors": [], "organization": None,
        "date": None, "keywords": [],
    }
    try:
        with zipfile.ZipFile(docx_path) as z:
            try:
                with z.open("docProps/core.xml") as f:
                    root = ET.parse(f).getroot()
                title = root.findtext("dc:title", namespaces=_NS_CORE)
                if title:
                    out["title_hint"] = title.strip()
                creator = root.findtext("dc:creator", namespaces=_NS_CORE)
                if creator:
                    out["authors"] = [creator.strip()]
                kw = root.findtext("cp:keywords", namespaces=_NS_CORE) or ""
                out["keywords"] = [k.strip() for k in kw.split(",") if k.strip()]
                modified = root.findtext("dcterms:modified", namespaces=_NS_CORE)
                if modified:
                    out["date"] = modified[:10]
            except KeyError:
                pass
            try:
                with z.open("docProps/app.xml") as f:
                    root = ET.parse(f).getroot()
                company = root.findtext("ext:Company", namespaces=_NS_APP)
                if company:
                    out["organization"] = company.strip()
            except KeyError:
                pass
    except (zipfile.BadZipFile, ET.ParseError):
        pass
    return out


def convert_docx(
    docx_path: Path,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
    strip_links_flag: bool = False,
) -> bool:
    if options is None:
        options = PipelineOptions(strip_links=strip_links_flag)

    out_name = sanitize_filename(docx_path.name)
    out_path = output_dir / out_name
    if out_path.exists() and not force:
        print(f"  SKIP (exists): {out_name}")
        return True

    try:
        with open(docx_path, "rb") as f:
            html_result = mammoth.convert_to_html(f)
        md_text = markdownify.markdownify(
            html_result.value,
            heading_style="ATX",
            strip=["img"] if not options.save_images else [],
            bullets="-",
        )
        md_text, warnings = pipeline.run(md_text, "text", options)

        props = _read_docx_metadata(docx_path)
        meta = SourceMeta(
            title_hint=props["title_hint"],
            authors=props["authors"],
            organization=props["organization"],
            date=props["date"] or date.fromtimestamp(docx_path.stat().st_mtime).isoformat(),
            keywords=props["keywords"],
            pages=None,
            word_count=len(md_text.split()),
            source_file=docx_path.name,
            source_url=None,
            doc_type="docx",
            extracted_via="mammoth+markdownify",
            lane="text",
        )
        full = compose(md_text, meta, options)

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(full, encoding="utf-8", newline="\n")
        wc = meta.word_count or 0
        suffix = f", {len(warnings)} warning(s)" if warnings else ""
        print(f"  OK: {out_name} ({wc} words{suffix})")
        return True

    except (OSError, ValueError) as e:
        print(f"  FAIL: {docx_path.name} -- {e}", file=sys.stderr)
        return False
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/integration/test_docx_mammoth_fallback.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add any2md/converters/docx.py tests/integration/test_docx_mammoth_fallback.py
git commit -m "feat(converters): DOCX converter on v1.0 pipeline with core.xml metadata"
```

---

## Task 26: PDF converter rewrite (pymupdf4llm only — Phase 1)

**Files:**
- Modify: `any2md/converters/pdf.py`
- Test: `tests/integration/test_pdf_pymupdf_fallback.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_pdf_pymupdf_fallback.py
"""Integration test: PDF converter (pymupdf4llm path)."""

import yaml

from any2md.converters.pdf import convert_pdf
from any2md.pipeline import PipelineOptions


def test_pdf_emits_v1_frontmatter_pymupdf_path(fixture_dir, tmp_output_dir):
    ok = convert_pdf(
        fixture_dir / "multi_column.pdf",
        tmp_output_dir,
        options=PipelineOptions(),
        force=True,
    )
    assert ok
    out_files = list(tmp_output_dir.glob("*.md"))
    assert len(out_files) == 1
    out = out_files[0].read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    body = out[end + 5:]
    assert fm["status"] == "draft"
    assert fm["extracted_via"] == "pymupdf4llm"
    assert fm["pages"] == 2
    assert fm["content_hash"]
    assert "Lorem ipsum" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_pdf_pymupdf_fallback.py -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite `any2md/converters/pdf.py`**

```python
"""PDF to Markdown converter (v1.0). Phase 1: pymupdf4llm only."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pymupdf
import pymupdf4llm

from any2md import pipeline
from any2md.frontmatter import SourceMeta, compose
from any2md.pipeline import PipelineOptions
from any2md.utils import sanitize_filename


def _parse_pdf_authors(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = []
    for sep in (";", ",", "&", "/"):
        if sep in raw:
            parts = [p.strip() for p in raw.split(sep) if p.strip()]
            break
    return parts or [raw.strip()]


def _parse_pdf_date(raw: str | None) -> str | None:
    """Convert 'D:20250315120000Z' -> '2025-03-15'."""
    if not raw:
        return None
    s = raw.lstrip("D:").strip()
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return None


def _parse_pdf_metadata(doc: "pymupdf.Document") -> dict[str, object]:
    meta = doc.metadata or {}
    return {
        "title_hint": (meta.get("title") or "").strip() or None,
        "authors": _parse_pdf_authors(meta.get("author")),
        "organization": (meta.get("creator") or "").strip() or None,
        "date": _parse_pdf_date(meta.get("creationDate")),
        "keywords": [k.strip() for k in (meta.get("keywords") or "").split(",") if k.strip()],
    }


def convert_pdf(
    pdf_path: Path,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
    strip_links_flag: bool = False,
) -> bool:
    if options is None:
        options = PipelineOptions(strip_links=strip_links_flag)

    out_name = sanitize_filename(pdf_path.name)
    out_path = output_dir / out_name
    if out_path.exists() and not force:
        print(f"  SKIP (exists): {out_name}")
        return True

    try:
        with pymupdf.open(str(pdf_path)) as doc:
            page_count = len(doc)
            md_text = pymupdf4llm.to_markdown(
                doc,
                write_images=False,
                show_progress=False,
                force_text=True,
            )
            props = _parse_pdf_metadata(doc)

        md_text, warnings = pipeline.run(md_text, "text", options)

        meta = SourceMeta(
            title_hint=props["title_hint"],
            authors=props["authors"],
            organization=props["organization"],
            date=props["date"] or date.fromtimestamp(pdf_path.stat().st_mtime).isoformat(),
            keywords=props["keywords"],
            pages=page_count,
            word_count=None,
            source_file=pdf_path.name,
            source_url=None,
            doc_type="pdf",
            extracted_via="pymupdf4llm",
            lane="text",
        )
        full = compose(md_text, meta, options)

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(full, encoding="utf-8", newline="\n")
        suffix = f", {len(warnings)} warning(s)" if warnings else ""
        print(f"  OK: {out_name} ({page_count} pages{suffix})")
        return True

    except (OSError, ValueError, RuntimeError) as e:
        print(f"  FAIL: {pdf_path.name} -- {e}", file=sys.stderr)
        return False
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/integration/test_pdf_pymupdf_fallback.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add any2md/converters/pdf.py tests/integration/test_pdf_pymupdf_fallback.py
git commit -m "feat(converters): PDF converter on v1.0 pipeline (pymupdf4llm path)"
```

---

## Task 27: CLI rewire — pass PipelineOptions through

**Files:**
- Modify: `any2md/cli.py`
- Test: `tests/cli/test_cli_existing_flags.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_cli_existing_flags.py
"""CLI smoke: existing v0.7 flags still work and route through v1.0 pipeline."""

import subprocess
import sys
from pathlib import Path

import yaml


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "any2md", *args],
        capture_output=True, text=True, cwd=cwd,
    )


def test_help_works():
    r = _run("--help")
    assert r.returncode == 0
    assert "any2md" in r.stdout.lower()
    assert "--strip-links" in r.stdout


def test_force_flag_overwrites(fixture_dir, tmp_output_dir):
    fixture = str(fixture_dir / "ligatures_and_softhyphens.txt")
    r1 = _run("-o", str(tmp_output_dir), fixture)
    assert r1.returncode == 0
    r2 = _run("-o", str(tmp_output_dir), fixture)  # skip-existing
    assert "SKIP" in (r2.stdout + r2.stderr)
    r3 = _run("-o", str(tmp_output_dir), "--force", fixture)
    assert r3.returncode == 0
    assert "OK" in (r3.stdout + r3.stderr)


def test_strip_links_propagates_to_pipeline_options(fixture_dir, tmp_output_dir):
    # We can't directly inspect PipelineOptions from CLI, but the converted
    # file should have v1.0 frontmatter regardless. Smoke that the flag is
    # accepted and conversion succeeds.
    r = _run(
        "-o", str(tmp_output_dir),
        "--strip-links",
        str(fixture_dir / "ligatures_and_softhyphens.txt"),
    )
    assert r.returncode == 0
    out = list(tmp_output_dir.glob("*.md"))
    assert len(out) == 1
    text = out[0].read_text()
    end = text.index("\n---\n", 4)
    fm = yaml.safe_load(text[4:end])
    assert fm["status"] == "draft"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_cli_existing_flags.py -v`
Expected: FAIL — current cli.py still expects converters' v0.7 signatures.

- [ ] **Step 3: Modify `any2md/cli.py`**

Find the section that calls `convert_url(...)` and `convert_file(...)`. Replace those calls with versions that pass `options`. Specifically:

1. After parsing `args`, add:
   ```python
   from any2md.pipeline import PipelineOptions
   options = PipelineOptions(strip_links=args.strip_links)
   ```

2. Replace the `convert_url(url, args.output_dir, force=args.force, strip_links_flag=args.strip_links)` call with:
   ```python
   result = convert_url(
       url, args.output_dir, options=options, force=args.force,
   )
   ```

3. Replace the `convert_file(file_path, args.output_dir, force=args.force, strip_links_flag=args.strip_links)` call with:
   ```python
   result = convert_file(
       file_path, args.output_dir, options=options, force=args.force,
   )
   ```

Read the current cli.py, identify the exact lines, then apply the Edit. The exact lines are 139-149 (URL loop) and 175-180 (file loop) of the current file.

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/cli/test_cli_existing_flags.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Run full test suite**

Run: `pytest -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add any2md/cli.py tests/cli/test_cli_existing_flags.py
git commit -m "feat(cli): Route through PipelineOptions; preserve v0.7 flags"
```

---

## Task 28: Snapshot tests — golden outputs

**Files:**
- Create: `tests/fixtures/snapshots/web_page.md`
- Create: `tests/fixtures/snapshots/ligatures_and_softhyphens.md`
- Create: `tests/fixtures/snapshots/multi_column.md`
- Create: `tests/fixtures/snapshots/table_heavy.md`
- Create: `tests/integration/test_snapshots.py`

- [ ] **Step 1: Write the snapshot harness**

```python
# tests/integration/test_snapshots.py
"""Snapshot tests: golden outputs for synthetic fixtures.

Snapshots are committed under tests/fixtures/snapshots/. To regenerate
after an intentional change run:
    UPDATE_SNAPSHOTS=1 pytest tests/integration/test_snapshots.py
"""

import os
from pathlib import Path

import pytest

from any2md.converters.docx import convert_docx
from any2md.converters.html import convert_html
from any2md.converters.pdf import convert_pdf
from any2md.converters.txt import convert_txt
from any2md.pipeline import PipelineOptions


SNAPSHOTS = {
    "web_page.html":                ("html",  convert_html),
    "ligatures_and_softhyphens.txt":("txt",   convert_txt),
    "multi_column.pdf":             ("pdf",   convert_pdf),
    "table_heavy.docx":             ("docx",  convert_docx),
}


def _normalize(text: str) -> str:
    """Strip volatile fields (date, content_hash) so snapshots are stable."""
    import re
    text = re.sub(r'^date: ".*?"', 'date: "<volatile>"', text, flags=re.MULTILINE)
    text = re.sub(r'^content_hash: ".*?"', 'content_hash: "<volatile>"', text, flags=re.MULTILINE)
    return text


@pytest.mark.parametrize("fixture_name", list(SNAPSHOTS))
def test_snapshot(fixture_name, fixture_dir, snapshot_dir, tmp_output_dir):
    _, convert = SNAPSHOTS[fixture_name]
    ok = convert(
        fixture_dir / fixture_name, tmp_output_dir,
        options=PipelineOptions(), force=True,
    )
    assert ok
    out = next(tmp_output_dir.glob("*.md"))
    actual = _normalize(out.read_text(encoding="utf-8"))

    snap_name = Path(fixture_name).stem + ".md"
    snap_path = snapshot_dir / snap_name

    if os.environ.get("UPDATE_SNAPSHOTS"):
        snap_path.write_text(actual, encoding="utf-8")
        return

    expected = snap_path.read_text(encoding="utf-8") if snap_path.exists() else None
    if expected is None:
        pytest.fail(
            f"Snapshot missing: {snap_path}. "
            f"Run UPDATE_SNAPSHOTS=1 pytest to create."
        )
    assert actual == expected, "Snapshot diff. Inspect or run UPDATE_SNAPSHOTS=1."
```

- [ ] **Step 2: Generate initial snapshots**

Run: `UPDATE_SNAPSHOTS=1 pytest tests/integration/test_snapshots.py -v`
Expected: all PASS, four `.md` files written under `tests/fixtures/snapshots/`.

- [ ] **Step 3: Verify diff-stable on a re-run**

Run: `pytest tests/integration/test_snapshots.py -v`
Expected: 4 PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_snapshots.py tests/fixtures/snapshots/
git commit -m "test: Snapshot tests for v1.0 output across all 4 formats"
```

---

## Task 29: Real-world spot check (test_docs/)

**Files:**
- Create: `scripts/validate-phase1.sh`

- [ ] **Step 1: Write the validation script**

```bash
#!/usr/bin/env bash
# scripts/validate-phase1.sh
# Manual validation against test_docs/ before tagging 1.0.0a1.
# This script is not run in CI — it's for the maintainer.

set -euo pipefail

OUT_DIR="$(mktemp -d)"
echo "Output directory: $OUT_DIR"

run_one() {
    local input="$1"
    echo "=== $input ==="
    python -m any2md -o "$OUT_DIR" --force "$input" || {
        echo "FAIL: $input" >&2
        return 1
    }
}

[[ -f test_docs/COMP4441-FinalProject-SafetyAlignmentEffectiveness-LLM-RockLambros.docx ]] \
    && run_one "test_docs/COMP4441-FinalProject-SafetyAlignmentEffectiveness-LLM-RockLambros.docx"

[[ -f "test_docs/ISO_IEC_27002_2022(en).pdf" ]] \
    && run_one "test_docs/ISO_IEC_27002_2022(en).pdf"

run_one "https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing"

echo
echo "Outputs:"
ls -la "$OUT_DIR"
echo
echo "Inspect each for: SAGE frontmatter, content_hash present, body NFC + LF, no garbled chars."
```

- [ ] **Step 2: Make executable + run**

Run:
```bash
chmod +x scripts/validate-phase1.sh
./scripts/validate-phase1.sh
```

Expected: outputs three `.md` files; eyeball each for:
- Frontmatter starts with `---\n`, ends with `\n---\n`.
- `status: "draft"`.
- `content_hash` is 64 hex chars.
- Body has correct title.
- No garbled characters (`?` blocks, `⌧`, etc.).
- For Wikipedia URL: no nav/footer noise; headings preserved.
- For ISO PDF: pages count correct (looks for `pages: NNN` matching what `pdfinfo` reports).
- For DOCX: tables are present in the body as Markdown pipes.

- [ ] **Step 3: Commit script**

```bash
git add scripts/validate-phase1.sh
git commit -m "chore: Add manual phase 1 validation script"
```

---

## Task 30: utils.py slim-down

**Files:**
- Modify: `any2md/utils.py`

- [ ] **Step 1: Identify what's still used**

Functions still imported elsewhere after Phase 1:
- `sanitize_filename` — used by all converters.
- `url_to_filename` — used by html.py and cli.py.
- `read_text_with_fallback` — used by html.py and txt.py.

Functions moved to `frontmatter.py` (delete from utils):
- `extract_title` → `derive_title` in frontmatter.py.
- `clean_markdown` → C5 stage in cleanup.py.
- `escape_yaml_string` → `_yaml_escape` in frontmatter.py (private).
- `strip_links` → kept as a Phase 4 candidate; for Phase 1, leave it but mark unused (delete in Phase 4 after `--strip-links` moves to pipeline gating).
- `build_frontmatter` → replaced by `frontmatter.compose`.

- [ ] **Step 2: Update `any2md/utils.py`**

```python
"""Shared utility functions for any2md.

Slimmed in v1.0: frontmatter and markdown cleanup moved to dedicated
modules (any2md/frontmatter.py, any2md/pipeline/cleanup.py).
"""

from __future__ import annotations

import re
import urllib.parse
from pathlib import Path

_CTRL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_SPECIAL_CHARS_RE = re.compile(r"[,;:'\"—–]")
_COLLAPSE_UNDERSCORES_RE = re.compile(r"_+")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def sanitize_filename(name: str) -> str:
    """Convert a source filename to a sanitized .md filename."""
    stem = Path(name).stem
    stem = _CTRL_CHARS_RE.sub("", stem)
    stem = stem.replace("/", "").replace("\\", "")
    stem = stem.replace(" ", "_")
    stem = _SPECIAL_CHARS_RE.sub("", stem)
    stem = _COLLAPSE_UNDERSCORES_RE.sub("_", stem)
    stem = stem.strip("_")
    if not stem:
        stem = "untitled"
    return stem + ".md"


def strip_links(text: str) -> str:
    """Replace markdown links with their display text. Used by --strip-links."""
    return _LINK_RE.sub(r"\1", text)


def read_text_with_fallback(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def url_to_filename(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    raw = parsed.netloc + parsed.path
    raw = raw.replace(".", "_").replace("/", "_")
    raw = raw.strip("_")
    raw = _COLLAPSE_UNDERSCORES_RE.sub("_", raw)
    return raw + ".md"
```

- [ ] **Step 3: Run full test suite**

Run: `pytest -v`
Expected: all green (nothing imports the removed helpers from utils anymore).

- [ ] **Step 4: Commit**

```bash
git add any2md/utils.py
git commit -m "refactor(utils): Slim utils.py; frontmatter/cleanup moved to dedicated modules"
```

---

## Task 31: CHANGELOG entry

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Append the 1.0.0a1 entry under `[Unreleased]` rename**

Replace the `## [Unreleased]` heading and contents with:

```markdown
## [1.0.0a1] — 2026-04-26

This is the first prerelease of any2md v1.0. Phase 1 of 5: foundation only.
No Docling, no new CLI flags. Output frontmatter has been rewritten to be
SAGE-compatible — this is a breaking change for downstream consumers
parsing v0.7 output. See `docs/superpowers/specs/2026-04-26-any2md-v1-design.md`
for the full v1.0 design.

### Added
- New `any2md/frontmatter.py` module (SAGE-compatible YAML emitter, `SourceMeta`).
- New `any2md/pipeline/` package with shared cleanup stages C1–C7
  (NFC normalization, soft-hyphen strip, ligature normalization,
  quote/dash normalization, whitespace collapse, footnote-marker strip,
  read-only validation).
- New `any2md/validators.py` (heading hierarchy + content_hash round-trip).
- Synthetic test fixtures under `tests/fixtures/docs/` plus a generator script.
- pytest test suite covering pipeline, frontmatter, validators, and per-format integration.

### Changed
- **BREAKING:** Output frontmatter shape is SAGE-compatible. New required fields:
  `document_id` (empty), `version`, `date`, `status: "draft"`, `document_type` (empty),
  `content_domain`, `authors`, `organization`, `generation_metadata`, `content_hash`.
  `source_file`, `pages`, `word_count`, and `type` are retained as any2md
  extension fields. See migration notes (forthcoming in Phase 4).
- Body is NFC-normalized with LF line endings before write (deterministic).
- All converters now route through the shared post-processing pipeline.
- `pyproject.toml`: added `[dev]` extras (pytest, pytest-snapshot, reportlab, ruff).
- `.gitignore`: now excludes `template/` and `test_docs/`.

### Carried forward unchanged
- All v0.7 CLI flags (`--input-dir`, `--output-dir`, `--force`, `--strip-links`,
  `--recursive`, `--max-file-size`).
- SSRF protection on URL fetching.
- File size limits.
- pymupdf4llm / mammoth / trafilatura backends (Docling is Phase 2).
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: CHANGELOG entry for 1.0.0a1"
```

---

## Task 32: Tag and TestPyPI release

**Files:**
- (none — git tagging + GitHub Release)

- [ ] **Step 1: Verify version, tests, lint**

Run:
```bash
ruff check . && ruff format --check .
pytest -v
python -c "import any2md; print(any2md.__version__)"
```

Expected: lint clean, all tests pass, version prints `1.0.0a1`.

- [ ] **Step 2: Confirm clean working tree**

Run: `git status`
Expected: `nothing to commit, working tree clean`.

- [ ] **Step 3: Push current branch**

Run: `git push origin <current-branch>`
Expected: success.

- [ ] **Step 4: Tag and push**

Run:
```bash
git tag -a v1.0.0a1 -m "any2md 1.0.0a1 — Phase 1 foundation prerelease"
git push origin v1.0.0a1
```

Expected: tag pushed.

- [ ] **Step 5: Create GitHub Release as prerelease**

Use `gh` CLI:

```bash
gh release create v1.0.0a1 \
    --prerelease \
    --title "any2md 1.0.0a1 — Phase 1 foundation" \
    --notes-from-tag
```

This triggers the existing `publish.yml` workflow, which (because `prerelease=true`) routes the build to TestPyPI.

- [ ] **Step 6: Verify TestPyPI publish**

Wait ~3–5 min, then:

```bash
pip install --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    "any2md==1.0.0a1" --target /tmp/any2md_test_install
ls /tmp/any2md_test_install
python -c "import sys; sys.path.insert(0, '/tmp/any2md_test_install'); import any2md; print(any2md.__version__)"
```

Expected: prints `1.0.0a1`.

- [ ] **Step 7: Smoke test the installed wheel**

Run:
```bash
PYTHONPATH=/tmp/any2md_test_install python -m any2md --help | head -5
PYTHONPATH=/tmp/any2md_test_install python -m any2md \
    -o /tmp/any2md_smoke tests/fixtures/docs/web_page.html
head -20 /tmp/any2md_smoke/web_page.md
```

Expected: help text shows; web_page.md has SAGE-compat frontmatter.

- [ ] **Step 8: Final commit (none needed — everything already committed)**

Phase 1 complete. Continue to Phase 2 plan when ready.

---

## Parallelism

The subagent-driven executor can dispatch the following groups in parallel (groups run sequentially, tasks within a group run concurrently):

```
[Group A — sequential prep]
Task 1 → Task 2

[Group B — parallel fixtures]  (after A)
Task 3, Task 4, Task 5, Task 6

[Group C — sequential types]   (after A)
Task 7 → Task 8

[Group D — parallel cleanup stages]  (after C)
Task 9, Task 10, Task 11, Task 12, Task 13, Task 14, Task 15

[Group E — parallel frontmatter helpers]  (after C)
Task 16, Task 17, Task 18, Task 19, Task 20

[Group F — sequential]  (after D + E)
Task 21 → Task 22

[Group G — parallel converter rewrites]  (after F + B)
Task 23, Task 24, Task 25, Task 26

[Group H — sequential]  (after G)
Task 27

[Group I — sequential]  (after H + B)
Task 28 → Task 29 → Task 30 → Task 31 → Task 32
```

Approximate critical path: A → C → D/E → F → G → H → I = 12 sequential task slots. With 4-way parallelism, total wall-clock is ~12 task-times (versus ~32 sequential).

---

## Self-review summary

Spec coverage:
- §3 Frontmatter contract → Tasks 8, 16–22 (full SAGE-compat shape, content_hash, all derivation helpers).
- §4 Pipeline (C1–C7) → Tasks 9–15. Text/structured lanes registered empty in Task 7 (Phase 2/3 fill them).
- §5 Per-format converters → Tasks 23–26 (TXT, HTML, DOCX, PDF). Phase 1 PDF is pymupdf4llm only.
- §6 CLI → Task 27 preserves v0.7 flags routing through new pipeline. New flags are Phase 4.
- §7 Documentation → Phase 4. Phase 1 only updates CHANGELOG.
- §8 Tests → present per-stage and per-converter; snapshot tests in Task 28; real-world validation in Task 29.
- §9 Phase 1 release gates → Task 32 (TestPyPI 1.0.0a1).

No placeholders or TBDs. All code blocks contain executable code. All commands have expected output.
