# Troubleshooting

Conversion-quality issues — output that looks wrong even though any2md
exited cleanly — are the dominant any2md bug class. This guide gives a
symptom-cause-fix table at the top, then expands each row into a deeper
diagnosis subsection below.

For orientation, see the [README](../README.md). For the output shape these
fixes target, see [output-format.md](output-format.md). For the pipeline
stages each artifact comes from, see [architecture.md](architecture.md).

## Quick triage

| Symptom | Likely cause | Quick fix |
|---|---|---|
| Garbled text, `?` blocks, or `⌧` characters | Encoding-broken PDF, often scanned with bad OCR layer baked in | Run `ocrmypdf` on the source first, then any2md. `--ocr-figures` won't help — the existing text layer is the problem. |
| Two columns interleaved | pymupdf4llm path on a multi-column PDF | `pip install "any2md[high-fidelity]"` so Docling preserves column flow |
| Tables show as plaintext blobs | DOCX with merged cells; mammoth fallback | `pip install "any2md[high-fidelity]"` so Docling parses DOCX directly |
| Many broken mid-paragraph line breaks | Text-lane T1 (`repair_line_wraps`) heuristic didn't match | File a conversion-quality issue with an input snippet |
| `content_hash` mismatch on round-trip | Body edited after generation, or the file was saved with CRLF line endings | Re-run any2md, or run `dos2unix output.md` |
| Output too verbose for RAG token budget | Default profile keeps more than a token-tight RAG index needs | Pass `--strip-links` and review whether `--ocr-figures` adds value for your corpus |
| `WARN: install Docling` keeps appearing | Repeatedly converting complex PDFs without Docling | Install `[high-fidelity]` once |
| `--strict` exit code 3 with no obvious problem | A non-fatal validator warning was emitted (heading hierarchy auto-fix, missing H1, paragraph dedupe) | Read the WARN block on stderr; either fix the source or drop `--strict` |
| `-H` exits with code 1 | `--high-fidelity` requested but Docling not installed | `pip install "any2md[high-fidelity]"` |
| `authors: []` on an academic PDF whose body shows a clear byline | v1.0/1.0.1 derived authors only from PDF `/Author` metadata; many academic PDFs leave that field empty | **Resolved by v1.0.2** — `heuristics.extract_authors` reads the body byline and (for arxiv-named PDFs) queries the arxiv API. Upgrade to `any2md>=1.0.2`. |
| `abstract_for_rag` is the byline, a cover-page blurb, or a TOC line | v1.0/1.0.1 took the first ≥ 80-char paragraph after H1 unconditionally | **Resolved by v1.0.2** — `heuristics.refine_abstract` prefers the body's `## Abstract` section and skips paragraphs matching byline/cover-blurb/TOC patterns. Upgrade. |
| `organization` populated with PDF software junk (`"LaTeX with acmart..."`, `"Adobe InDesign 16.2"`) | v1.0/1.0.1 used the PDF `/Creator` field as a fallback for `organization` | **Resolved by v1.0.2** — `heuristics.filter_organization` separates software values into the new `produced_by` extension field. Upgrade. |
| `&amp;`, `&lt;`, `&gt;`, or numeric HTML entities (`&#x2014;`) leak into the body | The Docling, mammoth+markdownify, and trafilatura paths all touch HTML internally; entities sometimes survive into the markdown | **Resolved by v1.0.2** — new shared cleanup stage **C8 `decode_html_entities`** runs `html.unescape()` on the body (outside fenced code blocks) at every profile. Upgrade. |
| ISO/IEC or technical-report PDF title shows as `"INTERNATIONAL STANDARD"` or `"TECHNICAL REPORT"` | v1.0/1.0.1 took the first H1 unconditionally; the cover-page H1 is boilerplate, not the title | **Resolved by v1.0.2** — `heuristics.refine_title` skips known cover-page boilerplate H1s and prefers the next H2. Upgrade. |
| Academic PDF body has a 50–80-line TOC table dumped right after the abstract | The structured-lane TOC is rendered as a GFM table; the existing T4 TOC heuristic only matches text-formatted TOCs | **Resolved by v1.0.2** — new text-lane stage **T7 `dedupe_toc_table`** drops table-formatted TOCs whose cells match later body headings. Upgrade. (Aggressive/maximum profiles only.) |
| `"Author's Contact Information:"` line in the body duplicates a byline | Academic PDFs often have a contact block right after the byline; v1.0/1.0.1 had no rule to drop it | **Resolved by v1.0.2** — new text-lane stage **T9 `strip_repeated_byline`** drops these lines (and indented continuations). Upgrade. |
| Wikipedia article output title has a `"Wikipedia:"` namespace prefix | trafilatura preserves the namespace prefix as part of the title; v1.0/1.0.1 emitted it verbatim | **Resolved by v1.0.2** — `heuristics.refine_title` strips `Wikipedia:` and `WP:` prefixes when `source_url` ends in `*.wikipedia.org`. Upgrade. |
| ISO cover-page QR-code blurb (`"Please share your feedback..."`, `"Third edition 2022-02"`) leaks into the body | The cover page bleeds into the extracted text on some PDFs | **Resolved by v1.0.2** — new text-lane stage **T8 `strip_cover_artifacts`** drops cover-page noise in the first ~30 lines, before the first H2. Upgrade. (Aggressive/maximum profiles only.) |
| Trafilatura web extraction leaves orphan `\|` or `>` lines, or short incomplete sentences | trafilatura sometimes emits extraction fragments that the existing pipeline didn't strip | **Resolved by v1.0.2** — new text-lane stage **T10 `strip_web_fragments`** drops these patterns. Upgrade. (Aggressive/maximum profiles only.) |
| `arxiv lookup ...` warning on stderr in airgapped environments | v1.0.2 enables arxiv API enrichment by default for filenames matching `\d{4}\.\d{4,5}` | Pass `--no-arxiv-lookup` to disable the lookup. See [cli-reference.md](cli-reference.md#--no-arxiv-lookup). |
| `title: ""` on an ISO/TR/whitepaper PDF whose first H1 is `"INTERNATIONAL STANDARD"` or similar boilerplate | v1.0.2 `refine_title` returned the first H2 from a single regex match without checking it was non-empty; emphasis-only H2s, NBSP-equivalent unicode, or regex `\s+` spans crossing into the next paragraph all produced an empty title | **Resolved by v1.0.3** — `refine_title` walks H2 lines line-by-line and skips any that strip to empty after dropping markdown emphasis. Upgrade to `any2md>=1.0.3`. |
| Docling output (PDF lane) keeps lone `\|` or `>` lines from malformed table parsing | T10 `strip_web_fragments` was text-lane-only by design (trafilatura-specific), so the structured lane never saw the orphan-punctuation filter | **Resolved by v1.0.3** — the lone-punctuation portion of T10 is extracted into a new lane-agnostic stage **`strip_orphan_punctuation`** that runs on Docling output too. The trafilatura short-fragment heuristic stays text-lane-only. Upgrade. |
| `&amp;amp;` (or other doubly-encoded entities) survives in body | Some extractors emit double-encoded entities; v1.0.2 ran a single `html.unescape` pass | **Resolved by v1.0.3** — C8 `decode_html_entities` now loops up to 5 iterations until output stabilizes. Upgrade. |
| Docling output (PDF lane) keeps `"Author's Contact Information:"`, leading TOC tables, or cover-page artifacts even after upgrading to v1.0.2 | T7/T8/T9 were registered only in the text-lane STAGES list; Docling output (`lane="structured"`) never saw them | **Resolved by v1.0.3** — those stages are now appended to the structured lane too. Upgrade. |

Each row maps to a section below.

## Garbled text, `?` blocks, or `⌧` characters

### What it looks like

The output body contains long runs of `?`, `⌧`, square boxes, or strings of
random-looking characters where readable text should be. Frontmatter is
populated normally; only the body is corrupted.

### Why this happens

The PDF has a broken text layer. Two common origins:

1. **Scanned-and-OCR'd PDFs** where the OCR tool produced an embedded text
   layer using a font subset that doesn't map back to legible characters.
   Older scanning tools sometimes embed character codes that point into a
   font CMap any2md can't resolve.
2. **CID-only fonts** where the PDF stores glyph IDs but no `ToUnicode` map.
   The renderer can display the page; text-extraction tools see opaque CIDs.

`--ocr-figures` does not help. That flag runs OCR on figure regions
specifically. The text-layer extractor still reads the broken characters
first.

### Diagnosis

Open the PDF in a viewer and try to copy a paragraph of text. If the
clipboard contents are nonsense, the text layer is the problem — not any2md.
If the clipboard contents are readable but any2md's output is not, the
issue is in extraction; file a conversion-quality issue with a copy of the
PDF (or a redacted equivalent) attached.

### Fix

Replace the broken text layer with a fresh OCR pass:

```bash
ocrmypdf scanned.pdf scanned-ocr.pdf
any2md scanned-ocr.pdf
```

[OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) replaces or supplements the
existing text layer with a fresh Tesseract OCR pass. The output PDF retains
its visual appearance but has a text layer any2md can read.

`ocrmypdf --redo-ocr` forces re-OCR even when a text layer exists, which is
what you want for the "broken layer" case. The default `--skip-text` path
preserves a working layer if one is detected.

## Two columns interleaved

### What it looks like

A multi-column PDF (academic paper, ISO standard, technical report) extracts
with text from the left column and right column interleaved on each line:

```
The system processes inputs in    The output module then writes
two stages. Stage one applies     results to the configured sink.
```

### Why this happens

You're on the pymupdf4llm fallback path and the PDF has multi-column layout.
pymupdf4llm extracts in y-coordinate order, which on a two-column page
produces left-line, right-line, left-line, right-line interleaving.

Confirm by inspecting the frontmatter:

```yaml
extracted_via: "pymupdf4llm"
```

If the value is `"docling"`, the column ordering should already be correct;
file a conversion-quality issue if it isn't.

### Fix

Install Docling:

```bash
pip install "any2md[high-fidelity]"
```

After install, any2md auto-detects Docling and uses it for PDF and DOCX. To
force it explicitly (and fail fast when it isn't installed), pass `-H` /
`--high-fidelity`. To require it as a CI gate, combine with `--strict`.

The new frontmatter will show `extracted_via: "docling"` and the columns
will read in source order.

The cost: Docling pulls in ~2 GB of ML models on first use and is 3–10×
slower than pymupdf4llm. For a corpus with mostly single-column documents,
the fallback path is sufficient and faster. For multi-column or
table-heavy corpora, the trade-off favors high-fidelity.

## Tables show as plaintext blobs

### What it looks like

A DOCX file contained a table (especially with merged cells, header rows
spanning multiple columns, or nested cells). The output flattens the table
into space-separated text:

```
Q1 2026 Q2 2026 Q3 2026 Q4 2026
Revenue 4.2 4.8 5.1 5.6
Cost 2.1 2.3 2.4 2.6
```

### Why this happens

You're on the mammoth+markdownify fallback path. mammoth's HTML conversion
loses merged-cell semantics, and markdownify's HTML-to-markdown step doesn't
reconstruct GFM tables from the resulting flat HTML.

Confirm:

```yaml
extracted_via: "mammoth+markdownify"
```

### Fix

Install Docling:

```bash
pip install "any2md[high-fidelity]"
```

Docling's DOCX parser handles merged cells, header rows, and nested tables
correctly. Output frontmatter will show `extracted_via: "docling"` and tables
will be GFM:

```markdown
|         | Q1 2026 | Q2 2026 | Q3 2026 | Q4 2026 |
|---------|---------|---------|---------|---------|
| Revenue | 4.2     | 4.8     | 5.1     | 5.6     |
| Cost    | 2.1     | 2.3     | 2.4     | 2.6     |
```

If your DOCX uses Word's "table styles" with complex header structures and
the Docling output still drops cells, file a conversion-quality issue.
Include the DOCX (or a redacted equivalent) and the 5-line snippet of the
bad output.

## Many broken mid-paragraph line breaks

### What it looks like

The output body has paragraphs split across many lines where they should be
joined:

```
The system processes inputs
in two stages.
Stage one applies preprocessing,
which includes NFC normalization
and deduplication.
```

### Why this happens

The text-lane T1 stage (`repair_line_wraps`) joins lines when the current
line ends in non-terminal punctuation, the next line starts lowercase, and
neither is structural (table row, list item, heading, fence). When that
heuristic doesn't fire — for instance, when wraps happen at sentence-final
punctuation but the source actually wanted those wraps preserved, or when
the input has unusual punctuation patterns — paragraphs stay split.

### Diagnosis

Identify the input pattern. For each broken paragraph, look at:

- The character at the end of each wrapped line. If it's `.`, `?`, `!`, `:`,
  T1 deliberately did not join (terminal punctuation is taken as
  paragraph-ending).
- The first character of the next line. If it's an uppercase letter, T1
  deliberately did not join (uppercase suggests a new sentence).
- Whether the lines are inside a list, table, code fence, or heading. T1
  skips structural lines entirely.

For most typical PDF / DOCX inputs, T1's defaults work. The "broken line"
symptom usually means the input pattern is unusual — for example, a
document where each line ends with a colon followed by a lowercase clause,
or where sentences happen to wrap at terminal punctuation by coincidence.

### Fix

This is a heuristic limitation, not a configurable knob. The repair is
defensive on purpose: aggressive joining corrupts tables and lists more
often than it fixes paragraph wraps.

If you encounter a corpus where T1 systematically under-joins, file a
conversion-quality issue with:

- A 5-line snippet of the bad output.
- The corresponding input snippet (or a redacted equivalent).
- The frontmatter `extracted_via` value (T1 only runs on text-lane backends).

T1's heuristic can be tuned for additional input patterns, but the change
needs concrete fixture inputs to test against.

## `content_hash` mismatch on round-trip

### What it looks like

A downstream consumer (your retrieval cache, a CI integrity check, a
re-validation step) computes the SHA-256 of the body and compares it to
`content_hash` in the frontmatter. They don't match.

### Why this happens

Two common causes:

1. **The body was edited after generation.** Even one whitespace change
   produces a different hash. The hash is the integrity check by design.
2. **Line endings were converted to CRLF.** Saving the file through a
   Windows editor (Notepad, some IDEs with default "platform line endings")
   converts the LF endings any2md wrote to CRLF. The recompute step in
   [output-format.md](output-format.md) does CRLF → LF normalization
   defensively, but only if the consumer uses that exact recipe.

### Diagnosis

Check whether the file has CRLF endings:

```bash
file output.md
```

The output should say `ASCII text` or `UTF-8 Unicode text`. If it says
`with CRLF line terminators`, that's the issue.

To check whether the body was edited, recompute the hash with the
NFC + LF normalization recipe from [output-format.md](output-format.md). If
it matches `content_hash`, the file is intact and the consumer's hash
computation is the bug. If it doesn't match, the body was edited.

### Fix

For CRLF line endings, normalize:

```bash
dos2unix output.md
```

For an edited body, either accept the edit (and re-run any2md to refresh
the hash) or restore the original from your version control:

```bash
any2md -f source.pdf
```

If the issue is reproducible from a clean any2md run (no edits, LF
endings), file a bug report — the v1.0 invariant is that
`compute_content_hash` over a written body matches the embedded hash.

## Output too verbose for RAG token budget

### What it looks like

You're feeding any2md output into a vector store with a token budget per
chunk, and your average chunk is larger than expected. Frontmatter looks
clean; the body is just longer than ideal.

### Why this happens

The default cleanup is "aggressive" but not "maximum." Markdown links,
inline footnote references that don't have a matching footnote section, and
verbose figure captions are preserved by default because they often carry
retrieval signal.

### Fix

Strip URL noise:

```bash
any2md --strip-links ./corpus
```

`--strip-links` removes markdown link URLs while preserving the link text.
For corpora where the URLs themselves are not the retrieval target (most
analytical content), this saves tokens without losing meaning.

Look at your `recommended_chunk_level`:

```yaml
recommended_chunk_level: "h2"
```

If your chunks are still too large, force `h3` chunking in your downstream
chunker. The recommendation is a heuristic — see
[output-format.md](output-format.md#chunking-guidance) for the threshold
calculation and how to override.

If the bulk of your token spend is figure captions or OCR'd image text,
reconsider `--ocr-figures`. That flag adds OCR text to the body, which
inflates the token estimate. For corpora where figures are decorative, the
default caption-only mode is leaner.

## `WARN: install Docling` keeps appearing

### What it looks like

Every run prints the install hint:

```
  WARN: report.pdf
        Multi-column / table-heavy PDF detected; pymupdf4llm may produce artifacts.
        For higher fidelity, install Docling:
            pip install "any2md[high-fidelity]"
        Or pass --high-fidelity to require it.
```

### Why this happens

The hint is rate-limited to once per process, but if you invoke any2md once
per file in a shell loop, each invocation is a new process and the hint
fires per file.

### Fix

Either install Docling once:

```bash
pip install "any2md[high-fidelity]"
```

…or invoke any2md once with multiple files instead of looping:

```bash
any2md -r ./corpus
```

A single invocation prints the hint at most once and proceeds with the
fallback for every file.

## `--strict` exit code 3 with no obvious problem

### What it looks like

```
$ any2md --strict report.pdf
Processing 1 file(s) → ./Text/

  OK: report.md  (Docling, structured, 14289 words, 18420 tok est, 1 warning)

Done in 4.2s: 1 converted, 0 skipped, 0 failed. 1 warning(s) — pass --strict to fail on warnings.
$ echo $?
3
```

The file converted cleanly but the exit code is 3.

### Why this happens

`--strict` promotes any pipeline validation warning to an exit code 3. The
warnings are non-fatal — the output file is written and is valid — but
`--strict` insists they not be present.

Common warning sources:

- **Heading hierarchy auto-fix.** S4 promoted a heading to H1 or demoted a
  duplicate H1; a level skip was flattened.
- **`H1 count is N (expected 1)`.** No H1 was promoted because no headings
  exist in the source. C7 reports this as a validator warning.
- **Paragraph dedupe.** T3 removed a duplicate paragraph from text-lane
  output.
- **TOC dedupe.** T4 removed a leading TOC block.

The full list of warnings is on stderr.

### Fix

Read the WARN block. The warnings are descriptive and identify the
file and the issue. From there:

- If the warning is benign for your pipeline (auto-fix you accept), drop
  `--strict` for that batch and use it only as a CI gate against
  regressions.
- If the warning indicates a real source-side problem (e.g. a document with
  no headings that you expected to have headings), fix the source.
- If the warning is a false positive from any2md's perspective, file a
  conversion-quality issue with the input.

## `-H` exits with code 1

### What it looks like

```
$ any2md -H report.pdf
  ERROR: Docling required for --high-fidelity / --ocr-figures / --save-images.
  pip install "any2md[high-fidelity]"
$ echo $?
1
```

### Why this happens

`-H` (and `--ocr-figures` and `--save-images`, which both imply `-H`)
require Docling. When Docling is not installed, the CLI exits before any
files are processed.

### Fix

Install Docling:

```bash
pip install "any2md[high-fidelity]"
```

If you don't want the high-fidelity install (it's ~2 GB of ML models), drop
`-H` and let any2md use the fallback path. The output will use pymupdf4llm
for PDFs and mammoth+markdownify for DOCX. For documents that don't have
multi-column layouts or complex tables, this is sufficient.

## When to file an issue

Two issue templates exist:

- **Generic bug report.** For CLI bugs, install issues, exit-code
  surprises, or behavior that doesn't match the documented contract.
- **Conversion quality.** For output artifacts — garbled text, broken
  tables, lost formatting, hash mismatches. Conversion-quality issues are
  unfixable without:
  - The source format (PDF / DOCX / HTML / TXT) and file size.
  - The Docling version (run `pip show docling` if installed).
  - The exact any2md invocation.
  - A 5-line snippet of the bad output.
  - What the source looks like at that location (text or screenshot, if
    non-confidential).

The conversion-quality template asks for all of these because they're
typically the minimum needed to reproduce.

## Cross-references

- [README](../README.md) — orientation and install paths.
- [cli-reference.md](cli-reference.md) — flag reference for the fixes
  referenced here.
- [output-format.md](output-format.md) — `content_hash` semantics and the
  recompute snippet.
- [architecture.md](architecture.md) — pipeline stage details for
  diagnosing why a particular artifact appeared.
- [upgrading-from-0.7.md](upgrading-from-0.7.md) — for users seeing
  v0.7-vs-v1.0 differences after an upgrade.

## Memory use in long-running processes

From v1.1.0, any2md keeps the Docling `DocumentConverter` (and its
loaded model weights) resident across the lifetime of the Python
process. This is intentional: it eliminates the ~2.5s cold-load tax
on every file in a batch. The trade-off is a sustained RSS floor of
roughly +535 MB once Docling has been imported (and more once a model
has actually loaded).

**For CLI users:** no action needed. The process exits when the batch
finishes; memory is freed.

**For library / embedder users** (importing any2md inside a
long-running service, notebook, batch worker):

```python
import any2md
from any2md.converters import convert_file

# Preferred: contextmanager
with any2md.docling_session():
    convert_file(some_pdf, out_dir)
    # ... more work ...
# Models freed here.

# Or imperative:
any2md.release_models()
```

Note: in v1.1.0 only `release_models` and `docling_session` are
re-exported from the top-level `any2md` package; `convert_file`
remains under `any2md.converters`.

`release_models()` is best-effort under thread contention — a thread
that starts a Docling build before `release_models()` returns may
re-populate the cache moments later. `docling_session()` is fine in
single-threaded contexts (the dominant library use case).

**To disable the cache entirely** (revert to v1.0.x per-call
construction behavior):

```bash
ANY2MD_DOCLING_CACHE=0 any2md ...
```

Note this trades ~2.5s per file for zero sustained memory beyond
each call's transient. Use it as a same-day workaround if the cache
is somehow misbehaving in your environment; if you reach for it
durably, please open an issue.

**Debugging cache hits/misses (v1.1.0):**

```python
from any2md._docling_cache import stats
print(stats())  # CacheStats(model_loads=N, cache_hits=N, ...)
```

A CLI flag (`--debug-cache-stats`) is planned for v1.2.0.

**Maintainer pre-release check:**

```bash
python scripts/bench_docling_cache.py
```

Asserts exactly one model load and a >=2x speedup on the second call.
Detects silent cache no-op (would be caused by a hypothetical future
Docling field with `default_factory` randomness).

**Fork after first convert is unsafe upstream.** Forking a process
after `convert()` has triggered model load inherits torch state via
shared file descriptors and process memory. The cache's `_after_fork`
hook resets cache structures but cannot heal torch's internal state.
Use `multiprocessing.set_start_method("spawn")` (the macOS default)
or call `release_models()` before fork.
