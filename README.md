<p align="center">
  <img src="assets/logo.png" alt="any2md" width="500"/>
</p>

# any2md

Convert PDFs, DOCX, HTML, URLs, and plain text into structured, machine-consumable Markdown for downstream RAG pipelines.

## What's new in 1.0.3

A patch release closing two regressions surfaced by audit on the v1.0.2-regenerated corpus, plus a Docling-lane reach for the v1.0.2 body-cleanup stages:

- **Empty-title fix**: cover-page-titled documents (`# INTERNATIONAL STANDARD` etc.) whose first H2 stripped to empty (markdown emphasis only, NBSP-equivalent unicode, regex span crossing into the next paragraph) emitted `title: ""`. `heuristics.refine_title` now walks H2 lines line-by-line and skips any that strip to empty after dropping markdown emphasis. The Wikipedia-prefix strip got the same non-empty guard.
- **Docling-lane orphan-punctuation**: lone `|` or `>` lines from Docling's malformed table parsing leaked through because T10 `strip_web_fragments` was text-lane-only by design. The orphan-punctuation portion is extracted into a new lane-agnostic stage `strip_orphan_punctuation` that runs on Docling output too. T10's trafilatura-specific short-fragment heuristic stays text-lane-only.
- **Lane-agnostic body cleanup on Docling lane**: T7 `dedupe_toc_table`, T8 `strip_cover_artifacts`, and T9 `strip_repeated_byline` are now appended to the structured-lane `STAGES` list, so Docling output gets the same body-cleanup pass that text-lane output already had.
- **Double-encoded HTML entities**: C8 `decode_html_entities` now loops `html.unescape` until output stabilizes (max 5 iterations) so `&amp;amp;` → `&amp;` → `&` is fully decoded.

The full design rationale lives in [docs/superpowers/specs/2026-04-26-v1.0.3-empty-title-orphan-punct-design.md](docs/superpowers/specs/2026-04-26-v1.0.3-empty-title-orphan-punct-design.md). Per-fix detail is in the [CHANGELOG](CHANGELOG.md). v1.0.2 highlights — `any2md/heuristics.py`, `produced_by`, C8, T7–T10, `--no-arxiv-lookup` — remain available; see [docs/superpowers/specs/2026-04-26-any2md-v1.0.2-design.md](docs/superpowers/specs/2026-04-26-any2md-v1.0.2-design.md).

## What this is

any2md ingests heterogeneous source documents and emits Markdown with a fixed YAML frontmatter contract. The frontmatter shape is SSRM-compatible (Structured Security Reasoning Markdown — a documented schema for LLM-consumable documents), so retrieval pipelines, embeddings jobs, and chunking utilities downstream can rely on field names, types, and a deterministic `content_hash` for cache invalidation. The body is NFC-normalized with LF line endings, and the heading hierarchy is guaranteed to start at H1 and not skip levels. The goal is one stable shape, regardless of whether a document started life as a scanned PDF, a Word doc, a Wikipedia page, or a plain text dump.

## Quick start

You'd run these three commands the first time you try the tool. Install, convert one local file, then convert one URL:

```bash
pip install any2md
any2md report.pdf
any2md https://en.wikipedia.org/wiki/Retrieval-augmented_generation
```

The first command pulls in the lightweight install (no Docling). The second writes `Text/report.md` next to your working directory. The third fetches the URL through trafilatura and writes a similarly-named `.md` file.

The output begins with frontmatter that looks like this:

```markdown
---
title: "Quarterly Financial Report"
document_id: ""
version: "1"
date: "2026-04-01"
status: "draft"
document_type: ""
content_domain: []
authors:
  - "Jane Smith"
organization: ""
generation_metadata:
  authored_by: "unknown"
content_hash: "a3f1...c91d"
token_estimate: 18420
recommended_chunk_level: "h2"
keywords: []
source_file: "report.pdf"
type: "pdf"
pages: 12
word_count: 14289
extracted_via: "pymupdf4llm"
---

# Quarterly Financial Report

Document content here...
```

Every field has a derivation rule, documented in [docs/output-format.md](docs/output-format.md).

## Why any2md

### The RAG ingestion problem

Building a retrieval pipeline means standing in front of a pile of source documents in different formats and producing one shape of input for an embedding model. Each format has its own pathologies:

- **PDFs** lose reading order in multi-column layouts, drop tables when extractors fall back to flat text, and embed soft hyphens (U+00AD) that look invisible but consume tokens.
- **DOCX** hides tables behind merged-cell artifacts when handled by HTML converters; metadata about authors and dates lives in `docProps/core.xml` and is easy to miss.
- **HTML pages** bury content under nav, cookie banners, and footer chrome that boilerplate strippers handle with varying degrees of correctness.
- **Plain text** has no structure at all — heading inference is the consumer's problem.

Ad-hoc converters often lose tables, scramble columns, or leave behind ligatures (`ﬁ`, `ﬂ`) and soft hyphens that quietly inflate token counts. The result is an inconsistent corpus: some chunks are clean, some are garbled, some have frontmatter, some don't. Downstream eval gets harder because you can't tell whether a poor retrieval result is a model problem or an ingestion problem.

### What "structured machine-consumable Markdown" means here

Three concrete things:

1. **A documented frontmatter contract.** Every field is either auto-derived or user-provided, with the derivation rule written down. Empty values are explicit (`""` or `[]`) rather than missing keys.
2. **A reproducible `content_hash`.** SHA-256 over the NFC-normalized body with LF line endings. Two converters running on the same input produce byte-identical output and the same hash. This is what makes downstream cache invalidation work.
3. **Heading hierarchy guarantees.** Exactly one H1, no skipped levels (an H2 → H4 jump is auto-corrected to H2 → H3 → H4). Chunkers that split on heading boundaries get a predictable structure.

### Honest comparison

| Tool | Strength | Where it fits | Where any2md differs |
|---|---|---|---|
| `unstructured.io` | Broad format coverage with a hosted API option; element-typed output (`Title`, `NarrativeText`, `Table`). | Pipelines that consume per-element JSON and chunk based on element types. | any2md emits a single Markdown stream with a fixed frontmatter; no element typing. |
| `pdfplumber` | Low-level access to PDF text positions, tables, and bounding boxes. | Custom extractors that need pixel-precise layout control. | any2md is a higher-level converter; it uses pymupdf4llm/Docling rather than wiring layout primitives by hand. |
| `pandoc` | Mature multi-format converter with rich filter ecosystem. | Document publishing, format-to-format conversion (Markdown → LaTeX, DOCX → HTML). | any2md is RAG-focused: stable frontmatter, content hashing, token estimation, and pipelines tuned for ingestion artifacts rather than rendering fidelity. |

If your pipeline already consumes element-typed JSON, `unstructured.io` is the better fit. If you need layout-precise PDF analysis, reach for `pdfplumber`. If you want a single CLI that emits one consistent Markdown shape for retrieval ingestion, that's where any2md sits.

## What you get

### Annotated frontmatter

Below is real output from converting a DOCX file. Each field carries a comment explaining what it is and why it's there:

```yaml
---
title: "Safety Alignment Effectiveness in LLMs"   # first H1 in body, or doc metadata title
document_id: ""                                    # empty unless you pass --auto-id
version: "1"                                       # "1" for source files without an embedded version
date: "2026-03-15"                                 # docx core props "modified" → ISO-8601
status: "draft"                                    # always "draft" for converted documents
document_type: ""                                  # SSRM controlled vocab — empty for non-security docs
content_domain: []                                 # SSRM controlled vocab — empty array when unknown
authors:                                           # extracted from docProps/core.xml dc:creator
  - "Rock Lambros"
organization: ""                                   # docProps/app.xml Company; empty when absent
generation_metadata:
  authored_by: "unknown"                           # any2md only converts; original authorship is undetermined
content_hash: "a3f1...c91d"                        # SHA-256 of NFC+LF body; reproducible
token_estimate: 18420                              # ceil(len(body)/4); rough but stable
recommended_chunk_level: "h3"                      # h3 because at least one H2 section > 1500 tokens
abstract_for_rag: "This paper investigates..."     # first prose paragraph after H1, ≤ 400 chars
keywords:                                          # docProps/core.xml cp:keywords → list
  - alignment
  - LLM safety
source_file: "safety-alignment.docx"               # original filename (any2md extension field)
type: "docx"                                       # source format (any2md extension field)
word_count: 14289                                  # any2md extension field
extracted_via: "docling"                           # which backend produced the markdown
produced_by: "Microsoft® Word for Microsoft 365"   # software that produced the source (new in v1.0.2)
---
```

Fields under `# any2md extension field` are retained from v0.7 for traceability and observability — they're not part of the SSRM contract proper, but they live in the same frontmatter block. See [docs/output-format.md](docs/output-format.md) for the full field reference.

### Before / after

A two-column page from a PDF. With pymupdf4llm alone (the lightweight fallback path), you get column interleaving:

```
The system processes inputs in    The output module then writes
two stages. Stage one applies     results to the configured sink.
preprocessing, which includes     Sinks include S3, local disk,
NFC normalization and             and the API endpoint described
deduplication.                    in section 4.
```

Through the Docling structured lane (the high-fidelity path), the same page reads in document order:

```
The system processes inputs in two stages. Stage one applies
preprocessing, which includes NFC normalization and deduplication.

The output module then writes results to the configured sink.
Sinks include S3, local disk, and the API endpoint described in
section 4.
```

The fallback path is good enough for single-column PDFs and most clean DOCX files. Multi-column or table-heavy sources benefit from `pip install "any2md[high-fidelity]"`. The decision tree in the next section makes this concrete.

The same reasoning applies to tables. With pymupdf4llm, a financial table with merged header cells often renders as flat lines:

```
Q1 2026 Q2 2026 Q3 2026 Q4 2026
Revenue 4.2 4.8 5.1 5.6
Cost 2.1 2.3 2.4 2.6
```

Through Docling's structured-lane table extractor, you get GFM tables that survive embedding and chunking:

```markdown
|         | Q1 2026 | Q2 2026 | Q3 2026 | Q4 2026 |
|---------|---------|---------|---------|---------|
| Revenue | 4.2     | 4.8     | 5.1     | 5.6     |
| Cost    | 2.1     | 2.3     | 2.4     | 2.6     |
```

Tables that survive conversion are tables your retrieval pipeline can actually return as evidence.

### Token estimates and chunking

`token_estimate` is `ceil(len(body) / 4)` — a stable approximation, not an exact tokenizer count. The point isn't precision; it's giving you a stable signal for budget calculations without pulling in `tiktoken` as a dependency.

`recommended_chunk_level` is the heading level we suggest splitting on for retrieval:

- `h2` when no H2 section's body exceeds 1500 estimated tokens.
- `h3` when any H2 section's body exceeds 1500 estimated tokens.

Concrete example: a 10K-token doc with five H2 sections averages 2K tokens per chunk at `h2` — comfortably inside a 4K context window. A 30K-token doc with three H2 sections would average 10K per chunk at `h2`, which is too large; `h3` is recommended so chunks stay closer to 2K. This is a heuristic — your retrieval evaluation should still drive the final choice. See [docs/output-format.md](docs/output-format.md) for the full chunking guidance.

## Installation

There are two install paths. Pick based on what your corpus contains.

### Lightweight (default)

You'd run this when you mostly handle clean single-column PDFs, well-formed DOCX, HTML, or plain text. Roughly 50 MB of dependencies, no ML models:

```bash
pip install any2md
```

The default backends are `pymupdf4llm` (PDF), `mammoth` + `markdownify` (DOCX), `trafilatura` (HTML/URL), and a heuristic structurizer (TXT). When you hand the tool a multi-column or table-heavy PDF without Docling installed, you'll see a one-time warning recommending the high-fidelity install.

### High-fidelity (Docling)

You'd run this when your corpus has multi-column PDFs, complex tables, or scanned documents you plan to OCR. Pulls in Docling and roughly 2 GB of ML models on first use; conversion is 3–10× slower than the fallback path but preserves layout that pymupdf4llm cannot:

```bash
pip install "any2md[high-fidelity]"
```

After install, the CLI auto-detects Docling and uses it for PDF and DOCX. To force it explicitly (and fail fast when it isn't installed), pass `-H` / `--high-fidelity`. To require it (treat fallback as an error), combine with `--strict`. Use `--backend pymupdf4llm` to force the lightweight backend even when Docling is installed (useful when Docling produces extraction artifacts on a specific input).

### When do I need high-fidelity?

Three questions, answer in order:

1. **Does my corpus contain tables I need to preserve?** If yes, install `[high-fidelity]`. The fallback DOCX path collapses merged cells; pymupdf4llm reconstructs simple tables but loses complex ones.
2. **Do my PDFs have multi-column layouts (academic papers, reports, ISO standards)?** If yes, install `[high-fidelity]`. pymupdf4llm interleaves columns on most multi-column pages.
3. **Are my PDFs scanned (no embedded text layer)?** If yes, install `[high-fidelity]` and pass `--ocr-figures`, OR run [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) on the source first. The fallback path produces empty output for scanned PDFs.

If all three answers are no, the lightweight install is sufficient.

## Usage by source type

### PDFs (digital)

You'd run this for any PDF where the text layer is intact (most files produced by Word, LaTeX, browser print-to-PDF). The default backend chain handles these without configuration:

```bash
any2md report.pdf
```

You'll see a one-line summary per file and a final batch summary:

```
  OK: report.md  (Docling, structured, 14289 words, 18420 tok est)

Done in 4.2s: 1 converted, 0 skipped, 0 failed.
```

Output lands in `./Text/` by default. Override with `-o ./other_dir/`.

### PDFs (scanned)

Scanned PDFs have no text layer — there's only a page image. You'd preprocess them with OCRmyPDF, which inserts a hidden text layer that any2md can then read:

```bash
ocrmypdf scanned.pdf scanned-ocr.pdf
any2md scanned-ocr.pdf
```

You'll see the same OK line as for digital PDFs. Alternatively, with `[high-fidelity]` installed, you can let Docling do the OCR pass:

```bash
any2md --ocr-figures scanned.pdf
```

`--ocr-figures` implies `--high-fidelity`. It's slower than running OCRmyPDF separately but doesn't require an extra tool in the pipeline.

### DOCX

You'd convert DOCX directly when colleagues hand you Word documents and you want them in your retrieval index. No flags needed:

```bash
any2md proposal.docx
```

You'll see the OK line with `extracted_via: docling` (if Docling installed) or `extracted_via: mammoth+markdownify` (fallback). Frontmatter pulls authors, organization, and modified date from `docProps/core.xml` and `docProps/app.xml` directly, with no `python-docx` dependency.

### HTML files and URLs

You'd run this to convert a saved HTML file or fetch a public URL. trafilatura strips boilerplate (nav, cookie banners, footer chrome) and produces clean Markdown:

```bash
any2md page.html
any2md https://en.wikipedia.org/wiki/Retrieval-augmented_generation
```

You'll see the OK line; for URL inputs, the frontmatter `source_url` field records the input URL and `date` is populated from the HTTP `Last-Modified` header (falling back to today's date).

**Warning:** URL fetching enforces SSRF protection. The resolved IP address is checked against private, reserved, loopback, and link-local ranges before any HTTP request is made. Only `http://` and `https://` schemes are accepted. File size is bounded by `--max-file-size` (default 100 MB). See the Security section below for the full trust model.

### Plain text

You'd run this when you have a `.txt` file with informal structure (headings as ALL-CAPS lines, indented bullet lists, code-shaped paragraphs) and want it normalized into Markdown:

```bash
any2md notes.txt
```

You'll see the OK line. The TXT converter runs a heuristic `structurize()` pass that infers headings, lists, and code blocks before handing off to the shared cleanup lane. Outputs are deterministic for a given input.

### Batch and directory mode

You'd run this when you have a directory of mixed source documents and want them all converted in one pass. Pass the directory as a positional argument; add `-r` to recurse into subdirectories:

```bash
any2md ./corpus/
any2md -r ./corpus/
```

You'll see one OK line per converted file followed by a final summary:

```
  OK: chapter1.md   (Docling, structured, 4127 words, 5300 tok est)
  OK: chapter2.md   (Docling, structured, 6203 words, 7800 tok est)
  OK: appendix.md   (trafilatura, text, 1893 words, 2400 tok est)

Done in 12.7s: 3 converted, 0 skipped, 0 failed.
```

You can also mix file paths, directories, and URLs in a single invocation:

```bash
any2md doc.pdf ./html_dump/ https://example.com/article notes.txt
```

The CLI classifies each argument and dispatches accordingly. Files that already exist in the output directory are skipped unless `--force` is set — this is the safe default for re-running over a partially-converted corpus. To regenerate everything (for instance, after upgrading any2md), pass `-f`:

```bash
any2md -f -r ./corpus/
```

You'll see the OK lines as if the conversion were fresh; previously-written outputs are overwritten.

## The output format

Every file converted by any2md has the same frontmatter shape, regardless of source format. The shape is **SSRM-compatible** — it matches the field names, types, and ordering of the Structured Security Reasoning Markdown specification, but values aren't required to match SSRM's controlled vocabularies (most converted documents aren't security research). Fields that require a controlled vocabulary (`document_type`, `content_domain`, `tlp`) are emitted empty unless you supply them via `--meta` or `.any2md.toml`.

### Field auto-fill summary

| Field | How it's filled |
|---|---|
| `title` | First H1 in body; falls back to source metadata title; falls back to cleaned filename. |
| `document_id` | Empty by default. Filled by `--auto-id` as `LOCAL-{YYYY}-DOC-{SHA8}`. |
| `version` | `"1"` for source files without an embedded version. |
| `date` | File `mtime` for local files; HTTP `Last-Modified` for URLs; today for TXT without mtime. |
| `status` | Always `"draft"` for converted documents. |
| `document_type`, `content_domain`, `tlp`, `frameworks_referenced` | Empty by default. User-provided via `--meta` or `.any2md.toml`. |
| `authors`, `organization`, `keywords` | Auto-extracted from source metadata when present; otherwise empty. |
| `generation_metadata.authored_by` | Always `"unknown"`. any2md only converts; it doesn't author. |
| `content_hash` | SHA-256 of NFC-normalized body with LF line endings. Always auto-computed. |
| `token_estimate` | `ceil(len(body) / 4)`. Always auto-computed. |
| `recommended_chunk_level` | `h2` or `h3` based on the size of the largest H2 section. |
| `abstract_for_rag` | First prose paragraph after H1, truncated to ≤ 400 chars. Skipped when `token_estimate < 500`. |
| `source_file`, `source_url`, `type`, `pages`, `word_count`, `extracted_via` | any2md extension fields, retained from v0.7 for traceability. |

The full reference — including type signatures, edge cases, and a Python snippet to recompute `content_hash` from a written file — lives in [docs/output-format.md](docs/output-format.md).

### Determinism

For a given input file and a given set of flags, any2md produces byte-identical output across runs. This matters for two practical reasons. First, your retrieval cache keys on `content_hash` only need to change when the source file actually changes, not when you happen to re-run the converter. Second, code review of converted corpora becomes meaningful — a non-zero diff on a re-conversion means someone changed either the source or the flag set, never the moon phase. The determinism boundary is the shared cleanup pass: NFC normalization, LF line endings, and a fixed pipeline stage order are what make this hold. Editing the body downstream invalidates the hash, which is intentional — the hash is the integrity check.

## Configuration

Two ways to override frontmatter values: the `--meta` flag for one-off invocations, and a `.any2md.toml` file for persistent organization-level defaults.

### `--meta KEY=VAL`

You'd use this when you want to set a frontmatter field on the command line without editing config files. Repeatable. Comma-separated values become arrays. Dotted keys set nested fields:

```bash
any2md --meta organization=OWASP \
       --meta authors="Alice, Bob" \
       --meta generation_metadata.authored_by=human \
       paper.pdf
```

You'll see the OK line as usual. The frontmatter of `Text/paper.md` will have `organization: "OWASP"`, `authors: ["Alice", "Bob"]`, and `generation_metadata.authored_by: "human"`. Override values always win over auto-derived values.

### `.any2md.toml`

You'd use this when you have a stable set of frontmatter defaults that should apply to every conversion in a project. The file is auto-discovered by walking up from the current working directory, so you can drop one at the root of your corpus repo and forget about it. Worked example for a security-research org producing SSRM-conforming outputs:

```toml
[meta]
organization = "Cloud Security Alliance"
document_type = "guidance"
content_domain = ["ai_security"]
frameworks_referenced = ["OWASP_LLM_TOP10", "NIST_AI_RMF"]
tlp = "TLP:CLEAR"

[meta.generation_metadata]
authored_by = "human_ai_collaborative"

[document_id]
publisher_prefix = "CSA"
type_code = "GD"
```

With this file in place and `--auto-id` passed, generated `document_id` values look like `CSA-2026-GD-a3f1c91d`. The resolution order, highest priority first: explicit `--meta KEY=VAL` arguments, then `--meta-file PATH` (when given), then auto-discovered `.any2md.toml`, then the tool's defaults. Full flag and config reference in [docs/cli-reference.md](docs/cli-reference.md).

### Network behavior

For PDFs whose filename matches the arxiv ID pattern (`\d{4}\.\d{4,5}`, e.g. `2501.17755v1.pdf`), any2md by default queries `https://export.arxiv.org/api/query` to enrich `authors`, `abstract_for_rag`, and `date` from the official arxiv metadata. The lookup is SSRF-guarded, has a 5-second timeout, and emits a non-blocking warning on any failure — conversion proceeds either way. Pass `--no-arxiv-lookup` to disable this for airgapped environments or when you want any2md to make no outbound calls. See [docs/cli-reference.md](docs/cli-reference.md#--no-arxiv-lookup) for details.

### Output verbosity and exit codes

The CLI has three verbosity flags that pair with a four-value exit-code contract:

- `--quiet` / `-q` suppresses the per-file `OK:` lines. Errors and the final summary still print. You'd use this in CI logs where every successful conversion is noise.
- `--verbose` / `-v` adds per-file pipeline stage timings, which is what you want when investigating a slow conversion or comparing backend performance.
- `--strict` promotes pipeline validation warnings (heading-hierarchy auto-fixes, missing H1, `content_hash` round-trip mismatches) into a non-zero exit. Useful in CI gates where you want a clean conversion or a build failure.

Exit codes:

| Code | Meaning |
|---|---|
| `0` | Success. All files converted (warnings may have been logged but didn't fail). |
| `1` | Usage or install error (unknown flag, missing required argument, `-H` requested without Docling installed). |
| `2` | At least one file failed entirely. |
| `3` | At least one file produced warnings AND `--strict` was set. |

## Troubleshooting

The five artifacts that account for most quality complaints:

- **Garbled text or `?` blocks.** The PDF's text layer is broken — usually a scanned document with bad OCR baked in by the scanning tool. `--ocr-figures` won't help because the problem is the existing text layer, not missing one. Run OCRmyPDF first to replace the broken layer.
- **Two columns interleaved on a multi-column PDF.** You're on the pymupdf4llm fallback path, which doesn't preserve column flow. Install `[high-fidelity]`.
- **Tables in DOCX render as plaintext blobs.** The mammoth fallback can't preserve merged cells. Install `[high-fidelity]` so Docling handles DOCX directly.
- **`content_hash` mismatch on round-trip self-check.** The body was edited after generation, or the file was saved with CRLF line endings (Windows editors are common culprits). Re-run any2md, or run `dos2unix` on the output.
- **Output is too verbose for your token budget.** The default profile preserves more than a token-tight RAG index needs. Pass `--profile maximum --strip-links` for the most aggressive minimization profile.

The full symptom-cause-fix triage guide, plus deeper diagnosis steps and follow-up errors for each row, lives in [docs/troubleshooting.md](docs/troubleshooting.md).

## Architecture

any2md uses a two-lane post-processing pipeline: one lane for layout-trustworthy backends (Docling), one for backends that need heavier text repair (pymupdf4llm, trafilatura, mammoth, the TXT heuristic). Both lanes converge on a shared cleanup pass, and the same `frontmatter.py` module emits YAML for every input format.

```
                  any2md  v1.0.3
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
             │  SourceMeta carries:
             │    organization, produced_by  ◀ NEW in v1.0.2
             │    (split via heuristics.filter_organization)
             │
       structured-md  structured-md   text-md
             │            │           │
             └─────┬──────┴───────────┘
                   ▼
        ┌─────────────────────────┐
        │  pipeline/structured.py │   structured lane
        │  S1 figure caption pass │   (trusts layout)
        │  S2 table compactor     │
        │  S3 cite normalizer     │
        │  S4 heading hierarchy   │
        │  T9 strip repeated      │   ◀ NEW v1.0.3
        │     byline              │
        │  T7 dedupe TOC table    │   ◀ NEW v1.0.3
        │  T8 strip cover         │   ◀ NEW v1.0.3
        │     artifacts           │
        │  strip_orphan_punct     │   ◀ NEW v1.0.3
        └────────────┬────────────┘
                     │
        ┌────────────┴────────────┐
        │     pipeline/text.py    │   text lane
        │  T1 line-wrap repair    │
        │  T2 dehyphenate         │
        │  T9 strip repeated      │   ◀ NEW (E1)
        │     byline              │
        │  T3 dedupe paragraphs   │
        │  T4 dedupe TOC block    │
        │  T7 dedupe TOC table    │   ◀ NEW (D1)
        │  T5 hdr/ftr strip       │
        │  T10 strip web          │   ◀ NEW (D2)
        │      fragments          │
        │      ↳ strip_orphan_punct  ◀ split out v1.0.3
        │  T6 list/code restore   │
        │  T8 strip cover         │   ◀ NEW (D3)
        │     artifacts           │
        └────────────┬────────────┘
                     │
        ┌────────────┴────────────┐
        │   pipeline/cleanup.py   │   shared lane
        │  C1 NFC normalize       │   (always last)
        │  C2 soft hyphen strip   │
        │  C3 ligature normalize  │
        │  C4 quote/dash normalize│
        │  C5 whitespace collapse │
        │  C8 decode HTML entities│   ◀ NEW (B1, all profiles)
        │  C6 footnote marker strip│
        │  C7 validate            │
        └────────────┬────────────┘
                     │
                     │           ┌──────────────────────────┐
                     │           │   any2md/heuristics.py   │  ◀ NEW v1.0.2
                     │           │  - refine_title          │
                     │           │  - refine_abstract       │
                     │           │  - extract_authors       │
                     │           │    (+ optional arxiv API)│
                     │           │  - filter_organization   │
                     │           └────────────┬─────────────┘
                     │                        │
                     ▼                        │
        ┌─────────────────────────┐           │
        │     frontmatter.py      │ ◀─────────┘   (consults heuristics
        │  - merge user overrides │                before YAML emission)
        │  - derive title/date/…  │
        │  - emit produced_by     │   ◀ NEW v1.0.2
        │  - compute content_hash │
        │  - emit YAML            │
        └────────────┬────────────┘
                     │
                     ▼
              <output>.md   ← frontmatter + cleaned body
```

The two-lane design exists because Docling output is layout-correct (running aggressive line-wrap repair on it would corrupt tables), while pymupdf4llm/trafilatura/TXT output benefits from heavier regex repair. The shared cleanup pass runs identically for both lanes — that's the determinism boundary that makes `content_hash` reproducible. v1.0.2 added a leaf `heuristics.py` module that `frontmatter.compose()` consults to refine the title, abstract, authors, and organization fields before YAML emission; new pipeline stages C8 and T7–T10 address concrete artifacts found in academic and standards-document PDFs. Full stage-by-stage contract reference, plus contributor guidance for adding new converters or pipeline stages, lives in [docs/architecture.md](docs/architecture.md).

## Migrating from v0.7

v1.0 emits SSRM-compatible frontmatter — that's the one intended breaking change. v0.7's small frontmatter (`title`, `source_file`, `pages`, `type`, `word_count`) becomes a fuller block with `document_id`, `version`, `date`, `status`, `content_hash`, `token_estimate`, `authors`, and several other fields. The v0.7 fields are retained as any2md extension fields in the same block, so traceability is preserved, but downstream parsers that expected the old fixed shape will need to update. The body is now NFC-normalized with LF line endings, which means `content_hash` is reproducible. If you need bit-for-bit v0.7 output, pin `any2md==0.7.0`. The full field-by-field migration guide and behavior-change list lives in [docs/upgrading-from-0.7.md](docs/upgrading-from-0.7.md).

## Security

any2md handles untrusted input (URLs, files of unknown provenance) and applies several defensive controls.

- **SSRF protection on URL fetching.** Before any HTTP request, the URL's hostname is resolved and the resulting IP is checked against private (RFC 1918), reserved, loopback, and link-local ranges. Hits in any of those ranges are rejected. The check happens in the connection adapter, so it covers redirects too — a public URL that 30x-redirects to `http://169.254.169.254/` (cloud metadata service) is still blocked.
- **Scheme allowlist.** Only `http://` and `https://` URLs are accepted. `file://`, `gopher://`, `data://`, and other schemes are rejected at argument parse time.
- **File size limits.** Local files larger than `--max-file-size` (default 100 MB) are skipped with a logged warning. URL responses are bounded by the same limit, enforced via streaming reads with a running byte counter so an oversize response is aborted mid-stream rather than buffered.
- **Filename sanitization.** Output filenames are stripped of control characters, null bytes, path separators, and Unicode dashes that look like ASCII hyphens. The output stays inside the configured `--output-dir`.
- **Trust model.** any2md is a converter, not a sandbox. It does not execute embedded scripts, macros, or JavaScript from any input format. PDFs, DOCX, and HTML are read for text content only — DOCX macros are not evaluated, PDF JavaScript actions are not invoked, and HTML `<script>` blocks are stripped before extraction. The tool processes whatever you point it at, so apply the same source-vetting practices you'd use for any document ingestion pipeline. URLs are fetched server-side from wherever any2md runs; if you run it on a machine with sensitive network access, the SSRF protections above are your primary defense, not the only one.

## Contributing

Issues, bug reports, and conversion-quality reports (the dominant any2md bug class — usually with attached output snippets) are all welcome. Setup, test commands, coding standards, and the release flow are documented in [CONTRIBUTING.md](CONTRIBUTING.md). When filing a conversion-quality issue, please use the `Conversion quality` issue template — it asks for the source format, file size, Docling version, full command, and a 5-line snippet of the bad output, all of which are typically required to reproduce the artifact.

## License

MIT.
