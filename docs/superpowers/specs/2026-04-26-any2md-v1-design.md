# any2md v1.0 — Design Specification

**Status:** approved
**Date:** 2026-04-26
**Author:** Rock Lambros (with Claude Code, brainstorming session)
**Target version:** 1.0.0
**Predecessor version:** 0.7.0

---

## 1. Goals and non-goals

### 1.1 Goals

1. **Eliminate conversion artifacts** that currently degrade output quality: garbled / missing text, lost tables and images, erratic reading order in multi-column documents, broken lines from PDF wrap-extraction, font-encoding artifacts (ligatures, soft hyphens, CID-font glyphs).
2. **Emit SAGE-compatible Markdown** — frontmatter shape and body conventions matching the `template/SAGE-Specification-v1.0-RC1.md` template in this repo, populated according to a documented derivation contract.
3. **Optimize the output for RAG and context engineering** — minimize file size and total tokens while remaining lossless on semantically meaningful content.
4. **Update all GitHub-facing documentation** to be deeply educational, not just reference.
5. **Ship as `1.0.0`** to PyPI (and TestPyPI for pre-release validation), signaling a stable RAG-ingestion contract.

### 1.2 Non-goals (deferred)

- SAGE `signature` block (key management out of scope for a CLI tool in v1.0).
- MkDocs / Sphinx site (GitHub-rendered Markdown only).
- New input formats beyond PDF / DOCX / HTML / URL / TXT (no XLSX, PPTX, EPUB, RTF).
- LLM-generated `abstract_for_rag` (heuristic is sufficient for v1.0).
- Strict SAGE conformance for non-security documents (we emit *compatible* shape, not strict validation).
- A `--dry-run` mode.

### 1.3 Locked decisions (from brainstorm Q&A)

| # | Decision | Choice |
|---|---|---|
| Q1 | SAGE conformance | **B — SAGE-compatible.** Same field shape; auto-fill what's truthful; leave domain-specific vocab fields empty; emit `status: "draft"`. |
| Q2 | PDF backend | **B1 + extras_require.** Docling primary; pymupdf4llm fallback when Docling not installed. Install via `pip install any2md[high-fidelity]`. Clear install hint when artifact-prone PDF detected without Docling. |
| Q3 | DOCX/HTML/TXT backends | **A.** Per-format best-of-breed: PDF → Docling, DOCX → Docling, HTML/URL → trafilatura, TXT → heuristic. trafilatura output goes through the same shared post-processing as everything else. |
| Q4 | Image / figure handling | **B by default** (caption only). `--ocr-figures` enables Tesseract OCR inside figures. `--save-images` writes image files to a sidecar dir and links them. |
| Q5a | Token-minimization aggressiveness | **Aggressive** (default). Lossless cleanup including TOC dedupe and footnote-marker stripping. |
| Q5b | Auto-derived SAGE fields | Auto: `content_hash`, `token_estimate`, `recommended_chunk_level`, `abstract_for_rag` (≥500 tok docs), `date`, `authors` (when extractable), `status: draft`. Opt-in: `document_id` via `--auto-id`. Empty: `document_type`, `content_domain`, `frameworks_referenced`, `tlp` (controlled vocabulary — not derivable). |
| Arch | Implementation shape | **Approach 1 + two-lane pipeline.** Functional `str → str` stages composed in fixed order. Two lanes (structured / text) merge into shared cleanup. |

---

## 2. Architecture overview

### 2.1 High-level data flow

```
                  any2md  v1.0
                       │
                  ┌────┴────┐
              CLI │ cli.py  │  parse args, classify URL/file/dir,
                  └────┬────┘  pick converter, route flags
                       │
            ┌──────────┼──────────┐
            ▼          ▼          ▼
   converters/    converters/    converters/
     pdf.py        docx.py     html.py  txt.py
        │            │            │       │
        │  Docling   │ Docling    │ trafi │ heuristic
        │  (primary) │ (primary)  │ latura│ structurize
        │  ↓ fallback│ ↓ fallback │       │
        │ pymupdf4llm│ mammoth+md │       │
        └────┬───────┴────┬───────┴───┬───┘
             │            │           │
       structured-md  structured-md   text-md
             │            │           │
             └─────┬──────┴───────────┘
                   ▼
        ┌─────────────────────────┐
        │  pipeline/structured.py │   structured lane
        │  - figure caption pass  │   (trusts layout)
        │  - table compactor      │
        │  - cite normalizer      │
        │  - heading hierarchy    │
        └────────────┬────────────┘
                     │
        ┌────────────┴────────────┐
        │     pipeline/text.py    │   text lane
        │  - line-wrap repair     │
        │  - dehyphenate          │
        │  - duplicate paragraph  │
        │  - TOC dedupe           │
        │  - hdr/ftr strip        │
        │  - list/code restore    │
        └────────────┬────────────┘
                     │
        ┌────────────┴────────────┐
        │   pipeline/cleanup.py   │   shared lane
        │  - NFC normalize        │   (always last)
        │  - soft hyphen strip    │
        │  - ligature normalize   │
        │  - quote/dash normalize │
        │  - whitespace collapse  │
        │  - footnote marker strip│
        │  - validate             │
        └────────────┬────────────┘
                     │
        ┌────────────┴────────────┐
        │     frontmatter.py      │   SAGE-compatible
        │  - merge user overrides │   YAML emitter
        │  - derive title/date/…  │
        │  - compute content_hash │
        │  - emit YAML            │
        └────────────┬────────────┘
                     │
                     ▼
              <output>.md   ← frontmatter + cleaned body
```

### 2.2 Module layout

```
any2md/
  cli.py                         (extended: new flags)
  utils.py                       (slimmed: most logic moves out)
  frontmatter.py                 (new: SAGE-compat YAML emitter, SourceMeta)
  pipeline/                      (new package)
    __init__.py                  (run(text, lane, options))
    structured.py                (Docling-lane stages)
    text.py                      (text-lane stages)
    cleanup.py                   (shared final stages)
  converters/
    __init__.py                  (extended dispatch)
    pdf.py                       (rewritten: Docling primary)
    docx.py                      (rewritten: Docling primary)
    html.py                      (extended: post-processing applied)
    txt.py                       (extended: cleanup pass added)
  validators.py                  (new, optional: SAGE-compat sanity warnings)

docs/
  output-format.md               (new — SAGE-compat contract)
  cli-reference.md               (new — flag-by-flag with use cases)
  architecture.md                (new — pipeline internals)
  troubleshooting.md             (new — symptom → cause → fix)
  upgrading-from-0.7.md          (new — migration guide)
  superpowers/specs/             (this file lives here)

.github/
  ISSUE_TEMPLATE/
    bug_report.md                (new)
    conversion_quality.md        (new)

README.md                        (rewritten for v1.0, deeply educational)
CHANGELOG.md                     (new entry: 1.0.0)
CONTRIBUTING.md                  (new)
pyproject.toml                   (extras_require, version 1.0.0)
.gitignore                       (add template/, test_docs/)
```

### 2.3 Key shape principles

- **Each converter's job shrinks** to: produce raw markdown + a `SourceMeta` object. No frontmatter, no cleanup — both are centralized.
- **Two pipeline lanes** because Docling-emitted markdown is layout-correct (don't run aggressive line-repair on it; tables would break); trafilatura/TXT/pymupdf4llm output benefits from heavier regex repair.
- **Shared cleanup runs last on both lanes**, identical for every input format. This is where lossless normalization lives. It is the determinism boundary that makes `content_hash` reproducible.
- **`frontmatter.py` is the only producer of the YAML block.** Centralizing this is what makes SAGE-compat output consistent across formats.
- **`SourceMeta` dataclass** carries per-converter signal (page count, word count, mtime, source URL, extracted authors) into `frontmatter.py` — converters no longer touch YAML.

---

## 3. SAGE-compatible frontmatter contract

### 3.1 Required-by-SAGE, auto-populated

| Field | Source | Notes |
|---|---|---|
| `title` | First H1 in extracted body; fallback: PDF/DOCX `dc:title` metadata; fallback: cleaned filename | YAML-escaped. Must be non-empty. |
| `document_id` | Empty by default. With `--auto-id`: `LOCAL-{YYYY}-DOC-{sha8(body)}` | Pattern-conformant; `LOCAL` reserved publisher prefix for unattributed conversions. Override prefix via `.any2md.toml`. |
| `version` | `"1"` for source files (no embedded version found); from PDF metadata if present | String per spec. |
| `date` | File `mtime` for local; HTTP `Last-Modified` for URL; today for TXT without mtime | ISO-8601 `YYYY-MM-DD`. |
| `status` | `"draft"` always (locked from Q1 = B) | Conformant value. |
| `document_type` | Empty `""` (controlled vocab — can't derive) | SAGE validators allow non-conforming when status=draft. |
| `content_domain` | Empty array `[]` | Controlled vocab — can't derive. |
| `authors` | PDF `Author` / DOCX `creator` / HTML `<meta name="author">`; else `[]` | Array even if single author. |
| `organization` | PDF/DOCX `Company` or HTML `og:site_name`; else `""` | |
| `generation_metadata.authored_by` | `"unknown"` | Documented extension value with rationale: any2md only converts; original authorship is undetermined. |
| `content_hash` | SHA-256 of NFC-normalized body, per SAGE §5.1 (LF line endings, NFC, hash bytes after the closing `---\n`) | Always auto-computed. 64-char lowercase hex. |

### 3.2 Optional, auto-populated

| Field | Source / heuristic |
|---|---|
| `keywords` | DOCX/PDF metadata keywords; HTML `<meta name="keywords">`; trafilatura categories |
| `frameworks_referenced` | Empty (would need term lookup against vocabulary) |
| `tlp` | Empty (security marking — not derivable) |
| `token_estimate` | `ceil(len(body_chars) / 4)` — 4 chars/token rough rule, no tiktoken dep |
| `recommended_chunk_level` | `h3` if any H2 section's body has > 1500 estimated tokens (using the same `ceil(chars/4)` heuristic as `token_estimate`); else `h2` |
| `abstract_for_rag` | First non-heading paragraph ≥ 80 chars after the H1, truncated to ≤ 400 chars at last sentence boundary. Skip emission if `token_estimate < 500`. |
| `source_file` / `source_url` | Preserved from any2md's existing convention as **non-SAGE extension fields** in the same frontmatter block — needed for traceability. |
| `type`, `pages`, `word_count` | Retained as v0.7-compatible extension fields for traceability and observability. |

### 3.3 Worked example

Input: `test_docs/COMP4441-FinalProject-SafetyAlignmentEffectiveness-LLM-RockLambros.docx`

```yaml
---
title: "Safety Alignment Effectiveness in Large Language Models"
document_id: ""                      # opt-in via --auto-id
version: "1"
date: "2026-03-15"                   # docx core props "modified"
status: "draft"
document_type: ""                    # SAGE-compat: empty for non-security docs
content_domain: []
authors:
  - "Rock Lambros"                   # docx core props "creator"
organization: ""
generation_metadata:
  authored_by: "unknown"
content_hash: "a3f1...c91d"          # 64-char hex
token_estimate: 18420
recommended_chunk_level: "h3"        # because some H2s > 1500 tok
abstract_for_rag: "This paper investigates whether current safety-alignment techniques in commercial LLMs withstand adversarial probing in the COMP4441 final-project context. Methods, metrics, and limitations are described."
keywords:
  - alignment
  - LLM safety
  - adversarial probing
source_file: "COMP4441-FinalProject-SafetyAlignmentEffectiveness-LLM-RockLambros.docx"
type: "docx"
word_count: 14289
---
```

### 3.4 Emitter invariants

1. **Frontmatter-then-body, separated by exactly `---\n` on a line by itself.**
2. **`content_hash` is computed *after* all post-processing is finalized.** Any further edit invalidates the hash.
3. **Body is NFC-normalized with LF line endings before hashing AND before writing to disk.** This makes recomputed hashes match.
4. **The emitter is deterministic.** Same input + same flags → byte-identical output.
5. **Field order in YAML matches SAGE §3.2 → §3.4 ordering.** Grouped: identity → classification → provenance → integrity → optional. Aids human diff/review.
6. **YAML escaping** is applied to every string field (existing `escape_yaml_string` covers it).
7. **Empty arrays appear as `[]`, empty strings as `""`.** Never omit a required-by-shape field, even when value is empty (it's part of the contract).

### 3.5 Validation (informational, non-fatal by default)

`validators.py` runs after frontmatter assembly and emits warnings (not errors) if:
- H1 count != 1
- Heading levels skip (e.g., H2 → H4)
- `content_hash` mismatch on round-trip self-check
- Body has zero content

Default: warnings to stderr. Flag `--strict` upgrades them to non-zero exit (useful in CI).

---

## 4. Post-processing pipeline

The pipeline is the answer to requirements #1 (artifact fixes) and #3 (token minimization). It is a flat list of named stages run in a fixed order. Each stage is a pure `str → str` function (one stage takes a small options object).

Lane assignment is decided once, by the converter, when it hands off to `pipeline.run(text, lane, options)`.

### 4.1 STRUCTURED lane (Docling output)

Docling produces correctly-laid-out markdown — multi-column flow is already resolved, tables already use GFM syntax, figures already have captions. Don't undo any of it.

| # | Stage | Purpose / artifact fixed | Notes |
|---|---|---|---|
| S1 | `lift_figure_captions` | Convert Docling's `<figure>` blocks to `*Figure N: caption*` italic lines. Drops the `<img>` reference unless `--save-images` is set. | Caption-only mode (Q4 default = B). With `--ocr-figures`, append OCR'd text below the caption. |
| S2 | `compact_tables` | Strip per-cell padding spaces inside GFM tables. Saves 5–8% on table-heavy docs. | Skip header alignment row to keep columns valid. |
| S3 | `normalize_citations` | Coalesce `[1] [2]` → `[1][2]`; ensure citations live at clause-end before punctuation, per SAGE §4.3. | Light-touch; only acts on existing bracket numerals. |
| S4 | `enforce_heading_hierarchy` | Guarantee single H1 (promote first heading if missing; demote subsequent H1s to H2). Ensure no skipped levels (H2 → H4 becomes H2 → H3 → H4). | Per SAGE §4.4. Emits validator warning when changes were applied. |

### 4.2 TEXT lane (trafilatura, TXT, pymupdf4llm fallback, mammoth fallback)

This output may contain raw line-wrap artifacts, soft-hyphenation, web boilerplate residue, or repeated TOC entries. Heavier repair lives here.

| # | Stage | Purpose / artifact fixed |
|---|---|---|
| T1 | `repair_line_wraps` | Join wrapped lines inside paragraphs. A line is a wrap when it ends with non-terminal punctuation **and** the next line starts lowercase **and** neither is in a code/table/list context. Fixes "broken lines." |
| T2 | `dehyphenate` | Merge `co-\noperation` → `cooperation`. Conservative — only when `[a-z]-\n[a-z]` and the joined word appears elsewhere in the doc, OR matches a small built-in English wordlist (`hyphen-en.txt`, ~10 KB). Avoids merging legit compound words like `co-pilot\nintegration`. |
| T3 | `dedupe_paragraphs` | Drop a paragraph if identical to the immediately preceding one (PDF over-extraction artifact). Hash-based, O(n). |
| T4 | `dedupe_toc_block` | Detect a leading TOC block (≥ 5 consecutive lines that match `^[\d.]+\s+.+\s+\d+$` or `^.+\.{3,}\s*\d+$`) and remove it if ≥ 70% of its entries reappear as H2/H3 headings later. Otherwise keep it. |
| T5 | `strip_running_headers_footers` | Heuristic: lines that appear ≥ 3× verbatim across page boundaries (Docling marks pages; pymupdf4llm fallback uses `\f` form-feed). Removes "Page 12 of 47" noise. **Only runs when page markers exist.** |
| T6 | `restore_lists_and_code` | Re-detect lost bullet/numbered lists from text-mode output (TXT lane already does most of this; harmless to re-run). Wrap likely code blocks (≥ 4 lines of monospace-shaped content) in fences. |

### 4.3 SHARED CLEANUP (always last; both lanes)

Lossless normalization. Required by the SAGE `content_hash` invariant — the body must be NFC + LF before hashing.

| # | Stage | Purpose |
|---|---|---|
| C1 | `nfc_normalize` | `unicodedata.normalize("NFC", text)` — required by SAGE §5.1. |
| C2 | `strip_soft_hyphens` | Remove U+00AD globally. Frequent PDF artifact, invisible but token-costly. |
| C3 | `normalize_ligatures` | NFKC pass *only on letter-presentation forms*: `ﬁ→fi, ﬂ→fl, ﬃ→ffi, ﬄ→ffl`, plus ` →' '` (NBSP). Whitelist-driven. |
| C4 | `normalize_quotes_dashes` | Smart quotes → straight; en/em-dash retained (semantic); ellipsis `…` → `...`. Saves ~1% on prose docs. |
| C5 | `collapse_whitespace` | Runs of spaces/tabs → single space; trim trailing whitespace per line; collapse 3+ blank lines → 2. |
| C6 | `strip_footnote_markers` | Remove inline footnote refs like `[^1]`, `¹`, `*1`, `(1)` from body when a recognizable footnotes section exists later. **Aggressive profile only.** Keeps the footnotes section intact. |
| C7 | `validate` | Read-only. Counts H1s, checks heading skips, computes round-trip `content_hash`. Emits warnings (or errors if `--strict`). Does not mutate text. |

### 4.4 Profile gating

| Stage | conservative | aggressive (default) | maximum |
|---|---|---|---|
| S1–S4 | ✓ | ✓ | ✓ |
| T1 line-wrap repair | ✓ | ✓ | ✓ |
| T2 dehyphenate | ✓ | ✓ | ✓ |
| T3 paragraph dedupe | ✓ | ✓ | ✓ |
| T4 TOC dedupe | – | ✓ | ✓ |
| T5 header/footer strip | ✓ | ✓ | ✓ |
| T6 list/code restore | ✓ | ✓ | ✓ |
| C1–C5 | ✓ | ✓ | ✓ |
| C6 footnote-marker strip | – | ✓ | ✓ |
| `--strip-links` | – | – | ✓ (auto-on at maximum) |

### 4.5 Implementation contract

```python
# any2md/pipeline/__init__.py
from typing import Callable, Literal
from dataclasses import dataclass

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

def run(text: str, lane: Lane, options: PipelineOptions) -> tuple[str, list[str]]:
    """Returns (cleaned_text, warnings)."""
```

- Every stage is registered in a module-level list per lane. Order is the source-of-truth for execution order.
- Stages may emit warnings via a contextvar; `run` collects them.
- No stage may raise on malformed-but-parseable input — if a regex doesn't match, the stage returns the input unchanged.
- Each stage has a single dedicated test file: `tests/unit/pipeline/test_<stage>.py` with at least one positive case, one negative case (no-op), and one edge case.

### 4.6 Performance budget

For a 100-page PDF on the Docling path, total pipeline time should be ≤ 10% of Docling extraction time. The pipeline operates on text only — no re-parsing, no re-rendering. All stages are linear in body length.

---

## 5. Per-format converter rewrites

### 5.0 Shared dataclass

```python
# any2md/frontmatter.py (excerpt)
@dataclass
class SourceMeta:
    title_hint: str | None         # PDF/DOCX dc:title, HTML <title>, etc.
    authors: list[str]             # extracted, may be []
    organization: str | None
    date: str | None               # ISO-8601
    keywords: list[str]
    pages: int | None              # PDFs only
    word_count: int | None         # DOCX/HTML/TXT
    source_file: str | None        # original file name
    source_url: str | None         # populated for URL inputs only
    extracted_via: str             # "docling" | "pymupdf4llm" | "mammoth+markdownify" | "trafilatura" | "heuristic"
    lane: Lane                     # "structured" | "text"
```

### 5.1 PDF converter

**Selection logic** (lazy import inside function):

```
try:
    import docling
    backend = docling
except ImportError:
    if pdf_looks_complex(pdf_path):
        warn(install_high_fidelity_msg)   # rate-limited to once per process
    backend = pymupdf4llm
```

**`pdf_looks_complex(pdf_path)` heuristic** (cheap, ~50 ms):
- Total pages > 5 **and**
- ≥ 2 columns detected on any sampled page (PyMuPDF block clustering by x-coords) **or**
- ≥ 1 table-like region detected (≥ 3 horizontal rules within 0.4 of page width) **or**
- Average chars-per-page < 200 (suggests scanned PDF — text layer mostly empty).

If all signals are absent, pymupdf4llm is good enough; suppress the install message.

**Docling path:**

```python
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions

opts = PdfPipelineOptions(
    do_ocr=False,
    do_table_structure=True,
    table_structure_options={"do_cell_matching": True},
    generate_picture_images=options.save_images,
)
if options.ocr_figures:
    opts.do_ocr = True
    opts.ocr_options = TesseractOcrOptions()

converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
result = converter.convert(pdf_path)
md_text = result.document.export_to_markdown()
lane = "structured"
extracted_via = "docling"
```

`SourceMeta` is filled from PyMuPDF metadata (cheap second-pass since Docling doesn't expose all fields cleanly):

```python
with pymupdf.open(str(pdf_path)) as doc:
    meta = doc.metadata or {}
    pages = len(doc)
authors = parse_pdf_authors(meta.get("author"))
date = parse_pdf_date(meta.get("creationDate"))
title_hint = meta.get("title") or None
keywords = [k.strip() for k in (meta.get("keywords") or "").split(",") if k.strip()]
```

**Fallback path (pymupdf4llm):**

```python
md_text = pymupdf4llm.to_markdown(
    doc,
    write_images=False,
    show_progress=False,
    force_text=True,
    page_chunks=False,
    table_strategy="lines_strict",
    margins=(0, 0, 0, 0),
)
lane = "text"
extracted_via = "pymupdf4llm"
```

### 5.2 DOCX converter

**Selection logic** mirrors PDF: Docling first, mammoth+markdownify on `ImportError`.

**Docling path:** Same `DocumentConverter` API, no pipeline options needed (DOCX parsed natively, no OCR). `lane = "structured"`.

**Fallback path:**

```python
with open(docx_path, "rb") as f:
    result = mammoth.convert_to_html(f)
html = result.value
md_text = markdownify.markdownify(
    html,
    heading_style="ATX",
    strip=["img"] if not options.save_images else [],
    bullets="-",
)
lane = "text"
extracted_via = "mammoth+markdownify"
```

**SourceMeta from DOCX core properties** — parse `docProps/core.xml` directly from the zip (zero new deps):

```python
import zipfile, xml.etree.ElementTree as ET
with zipfile.ZipFile(docx_path) as z:
    with z.open("docProps/core.xml") as f:
        root = ET.parse(f).getroot()
NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dcterms": "http://purl.org/dc/terms/",
}
title_hint = root.findtext("dc:title", namespaces=NS)
authors    = [root.findtext("dc:creator", namespaces=NS)]
keywords   = [k.strip() for k in (root.findtext("cp:keywords", namespaces=NS) or "").split(",") if k.strip()]
modified   = root.findtext("dcterms:modified", namespaces=NS)
date       = (modified or "")[:10] or None
```

`docProps/app.xml` parsed similarly for `Company` → `organization`.

### 5.3 HTML / URL converter

**No backend swap.** trafilatura stays primary because it's purpose-built for stripping web boilerplate, which Docling does not handle.

Changes:

1. After `trafilatura.extract`, also capture metadata via `trafilatura.bare_extraction(...)`:

   ```python
   bare = trafilatura.bare_extraction(raw_html, with_metadata=True, output_format="python")
   title_hint   = bare.get("title")
   authors      = [a.strip() for a in (bare.get("author") or "").split(",") if a.strip()]
   organization = bare.get("sitename")
   date         = bare.get("date")
   keywords     = bare.get("categories") or []
   ```

2. **HTTP `Last-Modified` for URL inputs.** Keep `trafilatura.fetch_url` as the primary fetch; add a single HEAD request after SSRF check passes to capture `Last-Modified`. Fall back to today's date if HEAD fails.

3. `lane = "text"` — trafilatura output isn't structurally trustworthy for table integrity. Shared cleanup runs as before.

4. `extracted_via = "trafilatura"` or `"trafilatura+bs4_fallback"`.

### 5.4 TXT converter

**Unchanged** structurize logic. Only the shared post-processing pipeline is now applied. `lane = "text"`. `SourceMeta` is minimal (title from H1 if structurize finds one; authors empty; date from mtime).

### 5.5 The new `convert_*` shape

Every converter follows the same template:

```python
def convert_pdf(path, output_dir, options: PipelineOptions, force=False) -> bool:
    # 1. produce raw markdown + SourceMeta
    md_text, meta = _extract(path, options)         # backend-specific
    # 2. run shared pipeline
    md_text, warnings = pipeline.run(md_text, meta.lane, options)
    # 3. compose frontmatter + body
    output = frontmatter.compose(md_text, meta, options)
    # 4. write
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / sanitize_filename(path.name)
    if out_path.exists() and not force:
        return _skip(...)
    out_path.write_text(output, encoding="utf-8", newline="\n")
    _log_result(path, output, warnings)
    return True
```

### 5.6 Behavior preserved from v0.7

- Skip-if-exists unless `--force`.
- File size limit (`--max-file-size`, default 100 MB).
- SSRF protection on URL inputs.
- `--strip-links` flag.
- Filename sanitization rules.
- Python 3.10+ floor.

### 5.7 Behavior intentionally broken in v1.0

- **Frontmatter shape** — described in §3; documented in `docs/upgrading-from-0.7.md`.
- **Output filename** — same convention, but Docling sometimes picks a better title than the filename heuristic, so the *frontmatter title* may differ from v0.7. Filename itself is unchanged.
- **CLI exit codes** — `--strict` adds non-zero exit on validation warnings. Default still exits 0 unless conversion fails entirely.

---

## 6. CLI surface, configuration, and error handling

### 6.1 v1.0 CLI

```
usage: any2md [-h] [--input-dir PATH] [--output-dir PATH] [-r] [-f]
              [--max-file-size BYTES]
              [--profile {conservative,aggressive,maximum}]
              [--strip-links]
              [-H] [--ocr-figures] [--save-images]
              [--auto-id] [--meta KEY=VAL] [--meta-file PATH]
              [--strict] [-q] [-v]
              [files ...]
```

| Flag | New? | Purpose |
|---|---|---|
| `files` | — | Files, directories, URLs (existing) |
| `--input-dir`, `-i` | — | Directory to scan (existing) |
| `--output-dir`, `-o` | — | Output dir, default `./Text` (existing) |
| `--recursive`, `-r` | — | Recurse subdirs (existing) |
| `--force`, `-f` | — | Overwrite existing `.md` (existing) |
| `--max-file-size` | — | Existing, default 100 MB |
| `--strip-links` | — | Existing — auto-on at `--profile maximum` |
| `--profile {…}` | new | Minimization aggressiveness; default `aggressive` |
| `--high-fidelity`, `-H` | new | Force Docling backend. Exit 1 with install hint if not installed. |
| `--ocr-figures` | new | Enable figure OCR. Implies `-H`. |
| `--save-images` | new | Save images to `<output>/images/`. Implies `-H`. |
| `--auto-id` | new | Generate `document_id` as `LOCAL-{YYYY}-DOC-{sha8(body)}`. |
| `--meta KEY=VAL` | new | Set/override any frontmatter field. Repeatable. Arrays via comma. Nested via dot. |
| `--meta-file PATH` | new | Load defaults from a TOML file. CLI `--meta` overrides file values. |
| `--strict` | new | Promote pipeline validation warnings to errors. |
| `--quiet`, `-q` | new | Suppress per-file `OK:` lines. |
| `--verbose`, `-v` | new | Print pipeline stage timings per file. |

### 6.2 Configuration file: `.any2md.toml`

Auto-discovered: walk up from `cwd`. Or explicit via `--meta-file`.

```toml
[meta]
organization = "Cloud Security Alliance"
document_type = "guidance"
content_domain = ["ai_security"]
frameworks_referenced = ["OWASP_LLM_TOP10", "NIST_AI_RMF"]
tlp = "TLP:CLEAR"

[meta.generation_metadata]
authored_by = "human_ai_collaborative"
model_id = "claude-opus-4-7"

[meta.authors]
default = ["Rock Lambros"]

[document_id]
publisher_prefix = "CSA"
type_code = "GD"
```

Resolution order (highest wins): explicit `--meta KEY=VAL` → `--meta-file` → auto-discovered `.any2md.toml` → tool defaults.

### 6.3 Default behavior matrix

| Scenario | Backend | Lane | Profile |
|---|---|---|---|
| `any2md doc.pdf` (Docling installed) | Docling | structured | aggressive |
| `any2md doc.pdf` (Docling absent, simple PDF) | pymupdf4llm | text | aggressive |
| `any2md doc.pdf` (Docling absent, complex PDF) | pymupdf4llm + warning | text | aggressive |
| `any2md -H doc.pdf` (Docling absent) | exit 1 with install hint | — | — |
| `any2md doc.docx` | Docling if installed, else mammoth | structured / text | aggressive |
| `any2md https://…` | trafilatura | text | aggressive |
| `any2md notes.txt` | heuristic | text | aggressive |

### 6.4 Error handling and exit codes

Per-file failures don't abort the batch (existing behavior preserved).

| Outcome | Exit code |
|---|---|
| All files converted, no warnings | 0 |
| All files converted, warnings present | 0 (with stderr summary) |
| ≥ 1 file failed entirely | 2 |
| ≥ 1 warning + `--strict` | 3 |
| CLI usage error / unknown flag | 1 |
| Docling forced (`-H`) but not installed | 1 + clear install hint |

### 6.5 Output text per file (default verbosity)

```
  OK: COMP4441-FinalProject.md  (Docling, structured, 14289 words, 18420 tok est, 2 warnings)
  OK: ISO_IEC_27002_2022.md     (Docling, structured, 87412 words, 110200 tok est)
  OK: en_wikipedia_org_wiki.md  (trafilatura, text, 4127 words, 5300 tok est)
  WARN: COMP4441-FinalProject.md
        - heading hierarchy: H2 → H4 skip at line 412 (auto-fixed)
        - duplicate paragraph removed at line 89

Done in 18.3s: 3 converted, 0 skipped, 0 failed.
2 warnings — pass --strict to fail on warnings.
```

### 6.6 Backend-not-installed message

Triggered when `pdf_looks_complex(...)` returns true and Docling is not importable:

```
  WARN: ISO_IEC_27002_2022.pdf
        Multi-column / table-heavy PDF detected; pymupdf4llm may produce artifacts.
        For higher fidelity, install Docling:
            pip install "any2md[high-fidelity]"
        Or pass --high-fidelity to require it.
```

Rate-limited via module-level flag to once per process.

### 6.7 Backward compatibility

- All v0.7 flags still work and behave identically when no new flag is set.
- v0.7 frontmatter shape is *not* preserved — sole intended break, called out in `CHANGELOG.md` and `docs/upgrading-from-0.7.md`.
- `mdconv.py` thin wrapper: keep, repoint to v1.0 entry. Print one-time deprecation note on stderr; remove in v1.1.

---

## 7. Documentation overhaul

User requirement: every GitHub-facing doc is **deeply educational** — not "here's what to type" but "here's how it works, why these choices, what to do when it goes wrong." Audience: a competent reader new to RAG document pipelines.

### 7.1 Document inventory

| File | New / Rewrite | Audience | Length budget |
|---|---|---|---|
| `README.md` | Rewrite | First-time visitor, decision-makers | ~600 lines |
| `docs/output-format.md` | New | Anyone consuming the `.md` output | ~400 lines |
| `docs/cli-reference.md` | New | Daily users | ~300 lines |
| `docs/architecture.md` | New | Contributors, advanced users | ~500 lines |
| `docs/troubleshooting.md` | New | Users seeing artifacts | ~300 lines |
| `docs/upgrading-from-0.7.md` | New | Existing v0.7 users | ~150 lines |
| `CHANGELOG.md` | Append | All | ~80 lines (1.0.0 entry) |
| `CONTRIBUTING.md` | New | Contributors | ~120 lines |
| `.github/ISSUE_TEMPLATE/bug_report.md` | New | Bug filers | ~40 lines |
| `.github/ISSUE_TEMPLATE/conversion_quality.md` | New | Artifact reporters | ~50 lines |

**Format**: GitHub-rendered Markdown only. No MkDocs / Sphinx. Keeps install path zero-config.

### 7.2 README.md skeleton

- One-paragraph "what this is" with RAG framing.
- Quick start (3 commands).
- **Why any2md** — RAG ingestion problem; what "structured machine-consumable Markdown" means; honest comparison table vs unstructured.io / pdfplumber / pandoc.
- **What you get** — annotated frontmatter example; before/after multi-column PDF excerpt; chunking guidance.
- **Installation** — base vs `[high-fidelity]`; "when do I need it?" decision tree.
- **Usage by source type** — PDFs (digital vs scanned), DOCX, HTML/URL, TXT, batch mode.
- **Output format** — link to `docs/output-format.md`; field auto-fill table.
- **Configuration** — `--meta` and `.any2md.toml` worked example.
- **Troubleshooting** — link with 5 most common artifacts.
- **Architecture** — link with two-lane diagram.
- **Migration from v0.7** — link.
- **Security** — SSRF, size limits, trust model.
- **Contributing**, **License**.

Tone rule: every command in the README is preceded by *why you'd run it* and followed by *what you'd see*. No raw command dumps.

### 7.3 docs/output-format.md sections

- Why a contract.
- The SAGE connection — what SAGE is, why we're compatible-not-strict, link to upstream spec.
- Field-by-field reference (every field: meaning, type, derivation, when empty, example, common-mistake callout).
- Body shape — single-H1 rule, citations, tables, footnotes; worked example showing 50-page PDF → markdown.
- `content_hash` semantics — exact normalization recipe; 6-line Python snippet that recomputes it.
- Chunking guidance — when to use h2 vs h3 for retrieval; concrete latency/recall tradeoffs.
- Validating output — `validators.py` programmatic use; auto-generated JSON Schema.

### 7.4 docs/cli-reference.md sections

Per-flag: one-line description; type/default; "use this when…"; "don't use this when…"; before/after example. Plus a worked-example matrix at the bottom for common scenarios.

### 7.5 docs/architecture.md sections

- High-level pipeline diagram.
- Why two lanes (with concrete damage example of running text-lane stages on Docling output).
- Stage catalog — every stage's contract.
- `SourceMeta` dataclass.
- Adding a new converter.
- Adding a new pipeline stage.
- Performance model.

### 7.6 docs/troubleshooting.md table

| Symptom | Likely cause | Fix |
|---|---|---|
| Garbled text / ⌧⍰⍰ | Encoding-broken PDF, scanned with bad OCR layer | OCRmyPDF first, then any2md |
| Two columns interleaved | pymupdf4llm path on multi-column PDF | Install `[high-fidelity]` |
| Tables show as plaintext blobs | DOCX merged cells; mammoth fallback | Install `[high-fidelity]` |
| Many broken mid-paragraph line breaks | T1 didn't match the join heuristic | File a bug with input snippet |
| `content_hash` mismatch on round-trip | Body edited after generation OR LF/CRLF mismatch | Re-run any2md or `dos2unix` |
| Output too verbose for RAG token budget | Default profile too gentle | `--profile maximum --strip-links` |
| `WARN: install Docling` keeps appearing | Repeatedly converting complex PDFs without Docling | Install once |

Each row links to a deeper subsection.

### 7.7 docs/upgrading-from-0.7.md sections

1. TL;DR.
2. Frontmatter field map (v0.7 → v1.0 table).
3. Behavior changes — exit codes, `--strict` mode, default backend, how to keep v0.7-like output.

### 7.8 CHANGELOG.md 1.0.0 entry

Keep a Changelog format. Sections: Added / Changed / Deprecated / Removed / Fixed / Security. Every breaking change in **Changed** with a one-line migration pointer.

### 7.9 CONTRIBUTING.md

- Dev setup (`pip install -e ".[dev,high-fidelity]"`).
- Running tests.
- Adding a converter / pipeline stage (cross-link to architecture.md).
- Coding standards (lazy imports, no class hierarchies for simple ops).
- Release flow (TestPyPI → PyPI, version bump, tag).

### 7.10 Issue templates

Two templates, because "conversion quality" complaints are the dominant any2md bug class and need different info than a normal bug:

- `bug_report.md` — generic.
- `conversion_quality.md` — asks for: source format, file size, Docling version, full command, **5-line snippet of bad output**, **what the source looks like at that location** (text or screenshot).

### 7.11 Editorial review pass

Before tagging 1.0.0:
- Every code block runs as written.
- Every cross-link resolves.
- No `TODO` / `TBD` / "coming soon" left.
- Spell-check.
- Read-aloud test — rewrite anything that reads like marketing copy.

---

## 8. Testing strategy

### 8.1 Framework

`pytest`. New dev deps: `pytest`, `pytest-snapshot` (or `syrupy`). Add `[dev]` extras to `pyproject.toml`.

### 8.2 Test layout

```
tests/
  unit/
    pipeline/
      test_repair_line_wraps.py
      test_dehyphenate.py
      test_dedupe_paragraphs.py
      test_compact_tables.py
      …                              # one file per stage
    test_frontmatter.py              # field derivation, hash, YAML escaping
    test_content_hash.py             # round-trip determinism
    test_validators.py
  integration/
    test_pdf_pymupdf_fallback.py
    test_pdf_docling.py              # skipif not docling
    test_docx_mammoth_fallback.py
    test_docx_docling.py             # skipif not docling
    test_html_trafilatura.py
    test_url_wikipedia.py            # the URL the user gave
    test_txt.py
  cli/
    test_cli_args.py
    test_cli_exit_codes.py           # 0 / 2 / 3
    test_cli_quiet_verbose.py
  fixtures/
    docs/
      multi_column.pdf               # ~5kb synthetic, owned
      table_heavy.docx
      ligatures_and_softhyphens.txt
      web_page.html
    snapshots/                       # golden outputs (committed)
      multi_column.md
      table_heavy.md
      …
  conftest.py
```

### 8.3 Test classes and coverage targets

| Class | Approach | Target |
|---|---|---|
| Pipeline stage units | Tabular `(input, expected)` per stage; positive, no-op, edge | ~95% line |
| Frontmatter | Field-by-field given `SourceMeta + options` | ~95% |
| `content_hash` round-trip | Build doc → hash → re-hash from disk → assert equal across CRLF/LF, BOM, NFC variants | 100% |
| Converters (integration) | Real fixture files; assert H1 present, table preserved, figure caption present, lane assignment, `extracted_via` | ~80% |
| CLI | `subprocess.run([sys.executable, "-m", "any2md", …])`; exit codes, stdout patterns | ~80% |
| URL fetch | One opt-in network test against the Wikipedia URL, marked `@pytest.mark.network` | — |

Overall target: 80%; 95% on `frontmatter.py` and `pipeline/cleanup.py`.

### 8.4 Fixtures

- **Owned synthetic** (~50 KB total, committed): tiny multi-column PDF generated via `reportlab` (added to `[dev]` extras), tiny merged-cell DOCX (built from XML at fixture-build time), HTML with boilerplate, TXT with ligatures/soft-hyphens. Deterministic, copyright-clean. Generation script `tests/fixtures/make-fixtures.py` is committed; outputs are also committed so test runs don't require regeneration.
- **Real-world** (`test_docs/` + Wikipedia URL): pre-release validation only, not committed, run by `scripts/validate-release.sh` before tagging.

### 8.5 Snapshots

Golden `.md` outputs under `tests/fixtures/snapshots/`. Diff tests fail on regressions. Updated by maintainer with `pytest --snapshot-update`.

### 8.6 Performance smoke

One test asserts a 100-page synthetic PDF converts in < 30 s on the pymupdf4llm path. Catches catastrophic regressions only.

---

## 9. Phasing and release plan

### 9.1 Phases

Five phases. Each ends with a TestPyPI alpha/beta tag. User can pause between any two.

| Phase | Scope | Tag | TestPyPI? | PyPI? |
|---|---|---|---|---|
| **1 — Foundation** | New module layout (`frontmatter.py`, `pipeline/`); `SourceMeta` dataclass; all shared cleanup stages C1-C7; rewire all 4 converters through new pipeline (no Docling yet); SAGE-compat frontmatter for all formats; content_hash + token_estimate + chunk_level + abstract derivation; existing CLI flags continue to work; **`.gitignore` adds `template/` and `test_docs/`** | `1.0.0a1` | ✓ | — |
| **2 — Docling backend** | `extras_require = {"high-fidelity": ["docling>=2.0"]}`; PDF/DOCX Docling primary path; `pdf_looks_complex` heuristic; install-hint message; `--high-fidelity` flag; structured-lane stages S1-S4; integration tests skipped when Docling not installed | `1.0.0a2` | ✓ | — |
| **3 — Figures / OCR / TXT cleanup** | Figure caption lift; `--ocr-figures`; `--save-images`; trafilatura post-processing wired; TXT lane through cleanup; metadata extraction (DOCX core props, PDF metadata, trafilatura `bare_extraction`, HTTP `Last-Modified`) | `1.0.0a3` | ✓ | — |
| **4 — Polish, configuration, docs** | `--meta`, `--meta-file`, `.any2md.toml` discovery, `--auto-id`, `--strict`, `--quiet`, `--verbose`; new exit codes; full doc rewrite (README + 6 `docs/*.md` + CONTRIBUTING + 2 issue templates); CHANGELOG 1.0.0; editorial review pass | `1.0.0rc1` | ✓ | — |
| **5 — Release** | Run `scripts/validate-release.sh` against real `test_docs/` files and Wikipedia URL; verify Docling install path on clean Mac and clean Linux; update GH Actions release workflow; final QA; tag and ship | `1.0.0` | (skip) | ✓ |

**Branch strategy**: long-running `v1.0` branch off `main`. Each phase is a PR into `v1.0`. Final phase merges `v1.0 → main` with the tag.

### 9.2 Pre-release gates

For every TestPyPI tag (`a1` … `rc1`):

- [ ] `pytest` green; coverage ≥ 80% overall; ≥ 95% on `frontmatter.py` + `pipeline/cleanup.py`.
- [ ] `python -m any2md test_docs/COMP4441-FinalProject…docx` produces output with non-empty title, ≥ 1 table preserved, no garbled characters.
- [ ] `python -m any2md test_docs/ISO_IEC_27002_2022\(en\).pdf` produces output with correct page count, multi-column flow correct (manual eyeball), tables preserved.
- [ ] `python -m any2md https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing` produces output with no nav/footer boilerplate, headings preserved.
- [ ] `content_hash` round-trip passes on all three outputs.
- [ ] `pip install -i https://test.pypi.org/simple/ any2md==<tag>` succeeds in clean Python 3.10 + 3.12 venvs.
- [ ] `pip install -i https://test.pypi.org/simple/ "any2md[high-fidelity]==<tag>"` succeeds in clean venv.

For the `1.0.0` tag, additionally:

- [ ] All docs read end-to-end with no `TODO`/`TBD`/dead links.
- [ ] Every code block in every doc runs as written.
- [ ] Migration doc tested by manually converting same DOCX with v0.7 vs v1.0 and diffing frontmatter.
- [ ] One real install from public PyPI in clean venv post-publish.

### 9.3 Release mechanics

1. **Trigger**: tag pattern. `vX.Y.Z` → PyPI. `vX.Y.ZaN` / `bN` / `rcN` → TestPyPI.
2. **Build matrix**: Python 3.10, 3.11, 3.12 × {base install, `[high-fidelity]` install}. Document the ~2 GB Docling model cache in workflow comments; consider model caching across CI runs.
3. **Smoke step**: after install, `python -c "import any2md"` and convert a tiny committed fixture (HTML, no Docling needed) to assert basic path works on the wheel.
4. **Publish**: `twine upload` with differing `TWINE_REPOSITORY_URL`. Trusted publisher (OIDC) preferred over API tokens.
5. **Release notes**: auto-generated from CHANGELOG.md `[1.0.0]` section.

### 9.4 Rollback

PyPI does not allow republishing a version. If `1.0.0` ships broken:

- Yank via PyPI web UI (`pip` refuses install, existing installs keep working).
- Cut `1.0.1` with the fix.
- Add CHANGELOG `[YANKED]` note.

### 9.5 Version classification

`0.7.0 → 1.0.0` (MAJOR bump under SemVer). Justification:
- Frontmatter schema breaks for downstream consumers.
- Tool moves from "evolving early-stage" to "stable RAG-ingestion-grade with documented contract."

---

## 10. Open questions

None. All five clarifying questions and the architectural fork were resolved during the brainstorm session.

---

## 11. Appendix: locked decisions trace

| Decision | Choice |
|---|---|
| SAGE conformance | B — SAGE-compatible |
| PDF backend | B1 + extras_require |
| DOCX/HTML/TXT backends | A (per-format best-of-breed) + uniform post-processing |
| Image / figure handling | B default; `--ocr-figures` for C; `--save-images` for D |
| Token minimization | Aggressive |
| SAGE derived fields | Recommended defaults |
| Implementation shape | Approach 1 + two-lane pipeline |
| Version bump | MAJOR (0.7.0 → 1.0.0) |
| Documentation requirement | All GitHub-facing docs deeply educational |
