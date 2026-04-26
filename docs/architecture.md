# Architecture

This document is for contributors and for anyone trying to understand how
any2md produces its output. It covers the pipeline shape, the stage catalog,
the `SourceMeta` contract, and the procedure for adding new converters or
stages.

For a user-facing orientation, see the [README](../README.md). For the output
shape this pipeline produces, see [output-format.md](output-format.md). For
the CLI surface that drives this code, see
[cli-reference.md](cli-reference.md).

## High-level data flow

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
        │     frontmatter.py      │   SSRM-compatible
        │  - merge user overrides │   YAML emitter
        │  - derive title/date/…  │
        │  - compute content_hash │
        │  - emit YAML            │
        └────────────┬────────────┘
                     │
                     ▼
              <output>.md   ← frontmatter + cleaned body
```

The diagram captures the three invariants that the rest of this document
unpacks: a converter produces raw markdown plus a `SourceMeta` and declares
its lane; the lane runs first, shared cleanup runs last, and `frontmatter.py`
is the only producer of the YAML block.

## Why two lanes

Different backends produce markdown of different trustworthiness. Docling's
output is structurally correct: tables are real GFM tables, multi-column
flow has been resolved, figures have captions, headings are at sensible
levels. The text-lane backends — pymupdf4llm fallback, trafilatura, mammoth,
the TXT heuristic — produce markdown that benefits from heavier regex repair.

The two lanes encode that distinction. Running the text-lane stages on
Docling output corrupts what Docling did right.

### Concrete damage example

This is what happens when the text-lane line-wrap repair (T1) runs on a
Docling-emitted GFM table:

Docling output (correct):
```markdown
| Quarter | Revenue | Cost |
|---------|---------|------|
| Q1 2026 | 4.2     | 2.1  |
| Q2 2026 | 4.8     | 2.3  |
```

After T1's heuristic incorrectly fires (incorrect, hypothetical):
```markdown
| Quarter | Revenue | Cost | |---------|---------|------| | Q1 2026 | 4.2     | 2.1  | | Q2 2026 | 4.8     | 2.3  |
```

T1 joins lines that don't end in terminal punctuation when the next line
starts lowercase. A pipe-delimited table row ends in `|`, not punctuation,
and a row that starts with `| Q1` starts with `|`, not an uppercase letter.
By the heuristic's letter, T1 should join — and that produces the corruption
above.

The actual T1 implementation guards against this with a structural-line check
(`_is_structural` recognizes table rows starting with `|`), but the broader
point is that a stage written for one input shape cannot be safely run on
the other. The two-lane separation makes that explicit at the architectural
level rather than relying on every stage to defensively detect every shape.

### Why shared cleanup is shared

The cleanup lane runs identically for both lanes. Its stages are lossless
normalizations that any well-formed markdown can absorb without harm:

- NFC unicode normalization
- soft hyphen removal
- ligature expansion (whitelist, not blanket NFKC)
- smart quote and ellipsis normalization
- whitespace collapse
- footnote-marker stripping (aggressive profile only)
- read-only validation

Centralizing these means `content_hash` is byte-deterministic: the same
post-cleanup body produces the same hash regardless of which lane ran first,
because the cleanup is the last thing that touched the bytes. This is the
determinism boundary the SSRM contract relies on.

## Stage catalog

Every stage is a pure `str → str` function with the signature:

```python
def stage(text: str, options: PipelineOptions) -> str: ...
```

Stages may emit non-fatal warnings via `pipeline.emit_warning()`, which the
runner collects. Stages must be no-ops on input they don't match: an
unmatched regex returns the input unchanged, never raises.

### Structured-lane stages (S1–S4)

Located in `any2md/pipeline/structured.py`. Run in the order listed before
shared cleanup, on Docling output.

| ID | Name | Lane | Input shape | Output shape | No-op cases | Edge cases |
|---|---|---|---|---|---|---|
| S1 | `lift_figure_captions` | structured | Markdown with `![alt](url)` images and HTML `<figure>...<figcaption>` blocks | Markdown with italic `*Figure: caption*` lines; image references kept only when `--save-images` | No images or figures present | Empty `alt` text drops the caption line entirely |
| S2 | `compact_tables` | structured | GFM tables with inconsistent per-cell padding | GFM tables with single-space cell padding; alignment row preserved | No table rows | Cells containing pipe-escaped content; alignment row identified by `^\|[\s:|-]+\|$` |
| S3 | `normalize_citations` | structured | Markdown with `[1] [2] [3]`-style spaced numeric citations | `[1][2][3]` (no spaces between adjacent numeric refs) | No spaced numeric citations | Non-numeric refs (`[Smith2020]`) are left alone |
| S4 | `enforce_heading_hierarchy` | structured | Markdown with any heading shape | Single H1, no skipped levels | Document has zero headings | First H1 absent: first heading promoted; subsequent H1s demoted to H2; H2 → H4 jump flattened to H2 → H3 → H4. Emits a warning when changes were applied. |

### Text-lane stages (T1–T6)

Located in `any2md/pipeline/text.py`. Run in the order listed before shared
cleanup, on text-lane output.

| ID | Name | Lane | Input shape | Output shape | No-op cases | Edge cases |
|---|---|---|---|---|---|---|
| T1 | `repair_line_wraps` | text | Paragraph text with single newlines mid-sentence | Paragraphs joined into single lines per logical paragraph | Inside fenced code blocks; lines that are structural (lists, tables, headings); lines ending in terminal punctuation; next line starts with uppercase letter | Tracks fence state across the document; never joins across blank lines |
| T2 | `dehyphenate` | text | `co-\noperation`-style word breaks | `cooperation` when joined word appears elsewhere in the document | Joined word does not appear elsewhere (preserves genuine compounds) | Same-document corroboration only — no external wordlist |
| T3 | `dedupe_paragraphs` | text | Paragraphs split by blank lines | Adjacent identical paragraphs collapsed to one | No adjacent duplicates | Whitespace-only differences are treated as identical (`.strip()` comparison) |
| T4 | `dedupe_toc_block` | text | TOC-shaped opening (≥ 5 entries matching `<title> <dots> <pagenum>`) followed by body whose H2/H3 headings cover ≥ 70% of the TOC entries | TOC block stripped | Profile is `conservative`; fewer than 5 TOC-shaped lines; overlap with body headings < 70% | Aggressive/maximum profiles only |
| T5 | `strip_running_headers_footers` | text | Multi-page output with `\f` form-feed page breaks | Page-repeated headers and footers removed | Document has fewer than 3 pages; no form-feed markers; no line repeats ≥ 3 times | Also strips `Page N of M` and bare-numeric footer lines when they appear on ≥ 3 pages |
| T6 | `restore_lists_and_code` | text | ≥ 4-line indented blocks (4 leading spaces) between blank lines | Indented blocks wrapped in fenced code | Already inside a fence; block has < 4 non-empty lines | Tracks fence state; preserves leading 4-space indent strip when wrapping |

### Shared cleanup stages (C1–C7)

Located in `any2md/pipeline/cleanup.py`. Run last, identically for both lanes.

| ID | Name | Lane | Input shape | Output shape | No-op cases | Edge cases |
|---|---|---|---|---|---|---|
| C1 | `nfc_normalize` | shared | Any unicode text | NFC-normalized text | Already-NFC text | Required by SSRM `content_hash` invariant |
| C2 | `strip_soft_hyphens` | shared | Text containing U+00AD (`­`) | Text without U+00AD | No soft hyphens | Soft hyphens are invisible but token-costly |
| C3 | `normalize_ligatures` | shared | Text containing presentation-form ligatures (`ﬁ`, `ﬂ`, `ﬃ`, `ﬄ`, `ﬅ`, `ﬆ`, `ﬀ`) and NBSP | Text with whitelist-expanded ligatures and regular spaces | None of the whitelist characters present | Whitelist-only — does not run blanket NFKC, which would fold superscripts and CJK compatibility characters |
| C4 | `normalize_quotes_dashes` | shared | Smart quotes (`“”‘’`) and ellipsis (`…`) | Straight quotes (`""''`) and three-dot ellipsis | No smart quotes or ellipsis | En-dash and em-dash are preserved (semantic) |
| C5 | `collapse_whitespace` | shared | Multiple spaces, trailing whitespace, ≥ 3 blank lines | Single inter-word spaces, trimmed line ends, blank-line runs capped at 2 | None of those patterns present | Inter-word run regex requires non-space on both sides |
| C6 | `strip_footnote_markers` | shared | Body with inline footnote refs (`[^1]`, `¹`-`⁹`, `⁰`) followed by a recognizable footnotes section heading | Body without inline markers; footnotes section preserved | Profile is `conservative`; no footnotes heading found | Heading regex accepts `## Footnotes`, `## Notes`, `## References` (case-insensitive) |
| C7 | `validate` | shared | Any post-cleanup body | Identical body (read-only) | Always read-only | Emits warnings via `emit_warning()` for H1 count != 1, heading skips |

### Profile gating

`PipelineOptions.profile` controls a small subset of stages.

| Profile | T4 (TOC dedupe) | C6 (footnote markers) |
|---|---|---|
| `conservative` | off | off |
| `aggressive` (default) | on | on |
| `maximum` | on | on |

All other stages run unconditionally. The default is `aggressive` because the
gated stages are net-positive for retrieval token budget on the documents we
test against (TOCs that mirror the body waste tokens; inline footnote markers
fragment paragraphs).

## The `SourceMeta` dataclass

`SourceMeta` is the contract between converters and `frontmatter.compose()`.
A converter produces raw markdown plus a `SourceMeta`; `compose` reads
`SourceMeta` and the post-pipeline body to fill the frontmatter fields.
Defined in `any2md/frontmatter.py`:

```python
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
    doc_type: Literal["pdf", "docx", "html", "txt"]
    extracted_via: Literal[
        "docling", "pymupdf4llm", "mammoth+markdownify",
        "trafilatura", "trafilatura+bs4_fallback", "heuristic",
    ]
    lane: Lane
```

### Field-by-field

| Field | Filled by | Required for SSRM contract |
|---|---|---|
| `title_hint` | All converters when source metadata has a title (PDF `/Title`, DOCX `dc:title`, HTML `<title>`, otherwise `None`) | No — `frontmatter.derive_title` falls back to first H1, then filename |
| `authors` | PDF (`/Author` parsed), DOCX (`dc:creator`), HTML (`<meta name="author">`), TXT (always `[]`) | No — empty `[]` is valid |
| `organization` | PDF/DOCX `Company`, HTML `og:site_name`, otherwise `None` | No — empty `""` is valid |
| `date` | PDF `creationDate`, DOCX `dcterms:modified`, URL `Last-Modified` HEAD response, file mtime, today | Yes — derived to today if all sources fail |
| `keywords` | PDF `/Keywords`, DOCX `cp:keywords`, HTML `<meta name="keywords">`, trafilatura `categories`, otherwise `[]` | No — emitted only when non-empty |
| `pages` | PDF only (page count via `pymupdf.open`); other formats `None` | No — extension field |
| `word_count` | DOCX, HTML, TXT (whitespace-split count); PDF `None` | No — extension field |
| `source_file` | All file inputs; URL inputs `None` | No — extension field |
| `source_url` | URL inputs only; file inputs `None` | No — extension field |
| `doc_type` | All converters | Yes — emitted as `type` in the YAML |
| `extracted_via` | All converters | Yes — non-SSRM extension but required for traceability |
| `lane` | All converters | Yes — drives pipeline routing |

The four "required" fields above are required for the v1.0 contract to be
fillable, not for SSRM strict conformance. Strict SSRM has a different
required-fields list — see [output-format.md](output-format.md) for that
distinction.

### Where converters draw the data

| Format | `title_hint` | `authors` | `organization` | `date` | `keywords` |
|---|---|---|---|---|---|
| PDF (Docling) | PyMuPDF `metadata["title"]` | PyMuPDF `metadata["author"]` parsed | PyMuPDF `metadata["author"]` (fallback only) | PyMuPDF `metadata["creationDate"]` parsed | PyMuPDF `metadata["keywords"]` parsed |
| PDF (pymupdf4llm fallback) | Same as above | Same as above | Same as above | Same as above | Same as above |
| DOCX (Docling) | `docProps/core.xml dc:title` | `dc:creator` (split on common separators) | `docProps/app.xml Company` | `dcterms:modified` (truncated to YYYY-MM-DD) | `cp:keywords` split on commas |
| DOCX (mammoth fallback) | Same as above | Same as above | Same as above | Same as above | Same as above |
| HTML / URL | trafilatura `title` | trafilatura `author` (split on commas) | trafilatura `sitename` | trafilatura `date` for HTML; HTTP `Last-Modified` HEAD for URL | trafilatura `categories` |
| TXT | None (always falls back to filename or H1) | `[]` | None | file mtime | `[]` |

The DOCX converters parse `docProps/core.xml` and `docProps/app.xml` directly
via `zipfile + xml.etree.ElementTree`. There is no python-docx dependency.

## Adding a new converter

Adding support for a new input format means writing a `convert_<format>`
function and registering it in the dispatcher. The pattern is mechanical
because frontmatter and cleanup are not the converter's job — those are
centralized.

### Step 1: Create `any2md/converters/<format>.py`

The function signature follows the existing converters:

```python
from pathlib import Path

from any2md.frontmatter import SourceMeta, compose
from any2md.pipeline import PipelineOptions, run as pipeline_run
from any2md.converters import add_warnings, is_quiet
from any2md.utils import sanitize_filename


def convert_<format>(
    file_path: Path,
    output_dir: Path,
    options: PipelineOptions,
    force: bool = False,
) -> bool:
    """Convert a <format> file to a Markdown file in `output_dir`.

    Returns True on success, False on failure.
    """
    # 1. Produce raw markdown + SourceMeta from the source file.
    raw_md, meta = _extract(file_path, options)

    # 2. Run the pipeline (lane is part of `meta`).
    cleaned, warnings = pipeline_run(raw_md, meta.lane, options)
    add_warnings(warnings)

    # 3. Compose frontmatter + body.
    output = compose(cleaned, meta, options, overrides=options.frontmatter_overrides)

    # 4. Write to disk.
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / sanitize_filename(file_path.with_suffix(".md").name)
    if out_path.exists() and not force:
        # caller already handled skip; this is a defensive check
        return False
    out_path.write_text(output, encoding="utf-8", newline="\n")

    # 5. Print the per-file summary line (unless --quiet).
    if not is_quiet():
        print(f"  OK: {out_path.name}  ({meta.extracted_via}, {meta.lane}, ...)")
    return True
```

`_extract` is the format-specific code. It produces a `(markdown, SourceMeta)`
tuple. The lane assignment lives inside `_extract` because it's a property of
the backend, not of the file format.

### Step 2: Register in the dispatcher

Edit `any2md/converters/__init__.py`:

1. Add the new extension to `SUPPORTED_EXTENSIONS`.
2. Add a branch to `convert_file` that imports and calls `convert_<format>`.

```python
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".txt", ".<new>"}

def convert_file(file_path, output_dir, options=None, force=False, ...):
    ext = file_path.suffix.lower()
    if ext == ".<new>":
        from any2md.converters.<format> import convert_<format>
        return convert_<format>(file_path, output_dir, options=options, force=force)
    # existing branches...
```

The import is inside the branch — that's the lazy-import pattern any2md uses
to keep startup time low when most invocations don't touch every backend.

### Step 3: Decide the lane

The lane decision rests on whether the new backend produces layout-trustworthy
markdown.

- **Pick `"structured"`** if the backend already produces correctly-laid-out
  GFM tables, multi-column flow, and accurate heading levels (Docling-class
  output).
- **Pick `"text"`** if the backend's output benefits from line-wrap repair,
  paragraph dedupe, hyphenation fixes, or list/code restoration. This is the
  more common case for new backends.

A single backend can hand off to either lane depending on what it can handle
— see how the PDF converter selects between Docling (`"structured"`) and
pymupdf4llm (`"text"`). The lane is set per-conversion in `SourceMeta.lane`.

### Step 4: Tests

Three categories of test, as fixtures and assertions:

1. **Unit test for `_extract`.** Given a fixture file, assert the
   `SourceMeta` fields you populate (title hint, authors, lane,
   `extracted_via`).
2. **Integration test for the full converter.** Given a fixture file, run the
   converter end-to-end, parse the output frontmatter, assert key fields are
   populated and that the body is non-empty.
3. **Snapshot test.** Generate a golden output `.md` once, commit it under
   `tests/fixtures/snapshots/`, then assert byte-equality on subsequent
   runs. Update with `pytest --snapshot-update` when intentional changes
   land.

The constraint is that **the converter must produce raw markdown plus a
`SourceMeta` and declare a lane. Frontmatter and cleanup are not its job.**
Every existing converter follows this rule. New converters that try to
write frontmatter directly, or run cleanup before handing off, break the
single-emitter invariant that makes `content_hash` reproducible.

## Adding a new pipeline stage

Adding a stage means writing a function, registering it in a `STAGES` list,
and writing tests.

### Step 1: Pick the lane

| You're fixing... | Lane |
|---|---|
| An artifact specific to layout-trustworthy backends (e.g. Docling) | `pipeline/structured.py` |
| An artifact specific to text-lane backends (line wraps, hyphens, deduplication) | `pipeline/text.py` |
| A lossless, format-agnostic normalization (unicode, whitespace) | `pipeline/cleanup.py` |

When in doubt, prefer text-lane. Cleanup-lane stages must be lossless and
shape-agnostic — they run on every output regardless of backend, so any bug
or false positive shows up everywhere.

### Step 2: Write the function

The signature is `(text: str, options: PipelineOptions) -> str`. The function
must be a pure transformation — no I/O, no side effects beyond
`emit_warning()`.

```python
import re

from any2md.pipeline import emit_warning
# ... other imports

_SOMETHING_RE = re.compile(r"...", re.MULTILINE)


def fix_my_artifact(text: str, options: "PipelineOptions") -> str:
    """One-line description.

    Longer explanation: what artifact this fixes, what no-op cases look
    like, what edge cases were considered.
    """
    if not _SOMETHING_RE.search(text):
        return text
    # transform
    return _SOMETHING_RE.sub(replacement, text)
```

Naming: verbs in snake_case. Existing names follow the pattern `<verb>_<thing>`
(`repair_line_wraps`, `dehyphenate`, `compact_tables`, `normalize_citations`).
Match the style.

### Step 3: Register in the lane's `STAGES` list

At the bottom of the lane module, append the function to `STAGES`. Order
matters — stages run in list order. Place the new stage where it makes sense
in the existing flow:

```python
STAGES.append(fix_my_artifact)
```

For cleanup-lane stages, the list is constructed in one literal at the
bottom of `pipeline/cleanup.py`. Insert the function in the order it should
run, between existing stages.

### Step 4: Tests

One file per stage in `tests/unit/pipeline/test_<stage_name>.py`. At minimum:

- **Positive case.** Input that triggers the stage, expected output.
- **No-op case.** Input that doesn't match — assert output equals input.
- **Edge case.** A boundary condition (empty string, single character,
  multi-line, fence-aware behavior, etc.).

```python
from any2md.pipeline import PipelineOptions
from any2md.pipeline.text import fix_my_artifact

OPTIONS = PipelineOptions()


def test_fixes_known_artifact():
    text = "...input that triggers..."
    expected = "...expected output..."
    assert fix_my_artifact(text, OPTIONS) == expected


def test_noop_on_unrelated_input():
    text = "...input that should not match..."
    assert fix_my_artifact(text, OPTIONS) == text


def test_handles_edge_case():
    # describe the edge condition in the test name
    ...
```

If the stage emits warnings, also test that the right warning fires for the
right input. The pipeline runner exposes warnings via the second return value
of `pipeline.run`.

## Performance model

any2md's wall-clock time per file decomposes into three phases. Knowing
where time goes is the first step to deciding whether an optimization is
worth pursuing.

### Phase A: Backend extraction

This is where most time is spent for large or complex inputs.

| Backend | Typical time per page (PDF) or per file | Why |
|---|---|---|
| `docling` | 0.5–3 seconds per page | ML models for layout analysis and table structure recognition |
| `pymupdf4llm` | 0.05–0.2 seconds per page | C-level PDF parsing without ML inference |
| `mammoth+markdownify` | 0.1–0.5 seconds per file | XML parsing of DOCX zip + HTML-to-markdown conversion |
| Docling (DOCX) | 0.5–2 seconds per file | DOCX is parsed natively by Docling without OCR |
| `trafilatura` | 0.05–0.2 seconds per file | HTML parsing with boilerplate detection |
| TXT heuristic | < 0.05 seconds per file | Pure regex over text |

Docling is slower because it loads ML models (~2 GB on first use, cached
afterwards) and runs them per page. The model load is one-time per process;
the per-page inference dominates for multi-page documents.

For PDFs, the `pdf_looks_complex` heuristic (in `any2md/_docling.py`) runs a
fast PyMuPDF block-clustering pass (~50 ms) to decide whether to print an
install hint when Docling is missing. That heuristic only runs when Docling
is not available — the goal is to surface the install recommendation only
when it would actually help.

### Phase B: Pipeline stages

The pipeline operates on text only — no re-parsing, no re-rendering. All
stages are linear in body length. For a 100-page PDF on the Docling path,
total pipeline time is typically under 10% of Docling extraction time.

Per-stage cost is dominated by regex compile-and-match. Each stage uses
module-level pre-compiled patterns to avoid the per-call compile overhead.

T2 (`dehyphenate`) builds a set of words present in the document — it's
linear in word count, with one pass to build the set and one to check
candidates. T4 (`dedupe_toc_block`) builds a set of body H2/H3 titles —
likewise linear.

The contextvar-based warning emission (`emit_warning()`) has negligible
overhead; it's only called when a stage emits a warning, which is rare in
practice.

### Phase C: Frontmatter assembly

Frontmatter is computed once per file. The cost is one SHA-256 over the body
(`compute_content_hash`), one regex pass for H1 / H2 detection
(`extract_abstract`, `recommend_chunk_level`), and a YAML-emit pass that's
linear in the number of fields. For a typical document, this phase is under
50 ms.

### Where the optimization opportunities are

In rough order of impact:

1. **Docling model warmup.** First-invocation latency includes 2–10 seconds
   of model load. For batch conversions, this is amortized; for single-file
   invocations, it dominates. A long-running daemon that holds Docling open
   between conversions would eliminate this. Out of scope for v1.0 (the
   project is a CLI, not a service).
2. **Parallel batch processing.** Currently sequential. Adding multiprocess
   parallelism for batch mode would scale linearly with cores for the
   pymupdf4llm path; for the Docling path, GPU contention may limit
   speedup.
3. **Pipeline stage fusion.** Stages that operate line-by-line could in
   principle be combined into a single pass. The current architecture
   prioritizes testability (one stage = one tested transformation) over
   raw speed; this trade-off is intentional.
4. **PDF complexity heuristic.** The 50ms cost of `pdf_looks_complex` is
   wasted when Docling is installed (the result is unused). Skipping the
   call when `has_docling()` returns true would save the cost; the savings
   are small per file but multiply across batches.

The pipeline is not the bottleneck for any backend except possibly the TXT
heuristic, where extraction is so fast that pipeline stages dominate.
Optimization effort is best spent on Phase A (extraction) for typical
workloads.

## Cross-references

- [README](../README.md) — the top-level orientation.
- [output-format.md](output-format.md) — the output shape this pipeline
  produces.
- [cli-reference.md](cli-reference.md) — the flags that drive
  `PipelineOptions`.
- [troubleshooting.md](troubleshooting.md) — symptom-cause-fix when the
  pipeline produces unexpected output.
- [upgrading-from-0.7.md](upgrading-from-0.7.md) — what changed in the
  pipeline shape between v0.7 and v1.0.
