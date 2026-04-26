# CLI reference

Every flag any2md accepts, with one-line description, type and default,
guidance on when you would and would not use it, and a small example. The
[worked-example matrix](#worked-example-matrix) at the bottom maps common
scenarios to full invocations.

For orientation, see the [README](../README.md). For the output shape these
flags affect, see [output-format.md](output-format.md). For the pipeline
internals, see [architecture.md](architecture.md).

## Invocation summary

```
any2md [-h] [--input-dir PATH] [--output-dir PATH] [-r] [-f]
       [--max-file-size BYTES]
       [--strip-links]
       [-H] [--ocr-figures] [--save-images] [--no-arxiv-lookup]
       [--auto-id] [--meta KEY=VAL] [--meta-file PATH]
       [--strict] [-q] [-v]
       [files ...]
```

`files` may be local file paths, directory paths, or `http://` / `https://`
URLs. They can be mixed in one invocation.

## Input and output

### `files` (positional)

One or more files, directories, or URLs. Default: scan the current directory
for supported files (`.pdf`, `.docx`, `.html`, `.htm`, `.txt`).

**Use this when** you have specific inputs to convert, or you want to mix
local files with URLs in a single batch.

**Don't use this when** you want to scan a different directory than the
current one — pass `--input-dir` instead.

```bash
any2md report.pdf notes.txt https://example.com/article ./more_docs/
```

### `--input-dir PATH`, `-i PATH`

Directory to scan for supported files. Mutually exclusive with positional
`files`.

**Use this when** you want a single tree-scan invocation in scripts where
shell globbing isn't reliable.

**Don't use this when** you have specific files or want to mix file types and
URLs — positional arguments are simpler.

```bash
any2md -i ./corpus
```

### `--output-dir PATH`, `-o PATH`

Output directory. Default: `./Text` relative to the working directory.

**Use this when** the default `Text/` collides with an existing directory, or
when your build pipeline expects outputs elsewhere (e.g. `./build/markdown/`).

**Don't use this when** you're prototyping — the default is fine.

```bash
any2md -o ./build/markdown report.pdf
```

You'll see output files written under `./build/markdown/` instead of `./Text/`.

### `--recursive`, `-r`

Recurse into subdirectories when scanning a directory.

**Use this when** your corpus is organized into subdirectories (`./corpus/2024/`,
`./corpus/2025/`) and you want one invocation to walk the whole tree.

**Don't use this when** the directory has children you don't want converted
(test fixtures, archived versions, etc.). Either move the directory or list
specific subpaths instead.

```bash
any2md -r ./corpus
```

You'll see one `OK:` line per discovered file plus a final summary.

### `--force`, `-f`

Overwrite existing output `.md` files.

**Use this when** you've upgraded any2md or changed flags and want to
regenerate a corpus that's already been converted.

**Don't use this when** you're running incremental conversions — the default
skip-if-exists behavior is what makes incremental runs cheap.

```bash
any2md -f -r ./corpus
```

You'll see `OK:` lines for files that previously would have shown `SKIP
(exists):`.

### `--max-file-size BYTES`

Maximum file size in bytes. Default: `104857600` (100 MB).

**Use this when** your corpus contains files larger than 100 MB that you want
to allow, or smaller than the default limit you want to enforce in CI.

**Don't use this when** you're processing typical documents — the default
covers everything but unusually large PDFs.

```bash
any2md --max-file-size 524288000 large_report.pdf
```

Files larger than the limit are skipped with a `SKIP (too large):` message and
counted in the final `skipped` total.

## Backend selection

### `--high-fidelity`, `-H`

Force the Docling backend for PDF and DOCX. Exits with code 1 and an install
hint if Docling is not installed.

**Use this when** you need consistent, layout-aware extraction across a corpus
— multi-column PDFs, complex tables, or files where the auto-detection might
not flip to Docling.

**Don't use this when** you only have plain HTML/URL/TXT inputs (Docling is
not used for those), or when Docling is not available in your environment and
the fallback path is acceptable.

```bash
any2md -H ./corpus
```

You'll see `extracted_via: "docling"` in the frontmatter of every PDF and DOCX
output. Without `-H`, any2md uses Docling when it's importable and falls back
silently otherwise.

### `--backend {docling,pymupdf4llm,mammoth}`

Force a specific extraction backend, overriding the automatic Docling-when-
installed selection. `docling` is equivalent to `--high-fidelity` (and shares
the same install pre-flight). `pymupdf4llm` forces the lightweight PDF
fallback even when Docling is installed. `mammoth` forces the lightweight
DOCX fallback even when Docling is installed.

The backend must match the input format. Mismatches fail per file rather
than the whole run:

- `--backend pymupdf4llm` on a DOCX → that file fails with a clear message;
  PDF inputs in the same run still convert.
- `--backend mammoth` on a PDF → that file fails with a clear message; DOCX
  inputs in the same run still convert.

**Use this when** Docling extracts incorrectly on a specific input (e.g.
[#13](https://github.com/rocklambros/any2md/issues/13) — Docling drops list
items on certain academic PDFs) and you want to fall back to the lightweight
backend without uninstalling Docling.

**Don't use this when** the auto-detection is doing the right thing — the
default behavior already prefers Docling when installed and falls back when
it isn't.

```bash
# Skip Docling for one specific PDF that triggers a known bug
any2md --backend pymupdf4llm research_paper.pdf

# Force Docling explicitly (same as --high-fidelity)
any2md --backend docling ./corpus
```

You'll see `extracted_via: "pymupdf4llm"` (or `"mammoth+markdownify"`, or
`"docling"`) in the frontmatter, matching the backend you forced.

### `--ocr-figures`

Run OCR on figures embedded in PDFs (Docling path). Implies `--high-fidelity`.

**Use this when** your PDFs contain text rendered as images — scanned charts
with embedded labels, screenshots of code, slides exported as images. The OCR
output is appended to the figure's caption.

**Don't use this when** your PDFs are digital (text layer intact) — OCR is
slow and adds noise. For fully scanned PDFs (no text layer at all), prefer
running [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) on the source first;
that produces a real text layer the rest of the pipeline can use.

```bash
any2md --ocr-figures slides.pdf
```

You'll see `OK:` lines that take longer than usual — figure OCR runs Tesseract
per figure region.

### `--no-arxiv-lookup`

Disable the arxiv API metadata enrichment for PDFs. **Default: enabled.**

For PDFs whose filename matches the arxiv ID pattern (`\d{4}\.\d{4,5}` —
e.g. `2501.17755v1.pdf`, `1706.03762.pdf`), any2md by default queries
`https://export.arxiv.org/api/query?id_list={arxiv_id}` to enrich the
frontmatter with the official `authors`, abstract, and `date` from arxiv.
The lookup is SSRF-guarded (resolved IPs checked against private, reserved,
loopback, and link-local ranges), has a 5-second timeout, makes a single
attempt with no retry, and emits a non-blocking warning on any failure
(network error, HTTP non-200, XML parse error). Conversion never fails
because of arxiv unreachability.

**Use this when** you're running any2md in an airgapped environment, on a
build agent that's not allowed to make outbound calls, or when you want a
guarantee that no network traffic leaves the host during conversion. Also
useful when arxiv is rate-limiting your IP and you'd rather not see the
warnings on every run.

**Don't use this when** you're processing arxiv-named PDFs and you want the
authoritative author list and abstract — the on-disk PDF often has incomplete
or missing metadata, and the arxiv API is the canonical source. The default
(enabled) is the right choice for most online conversions.

```bash
# Disable the lookup for one batch
any2md --no-arxiv-lookup ./papers/

# Equivalent for a single file
any2md --no-arxiv-lookup 2501.17755v1.pdf
```

You'll see frontmatter populated only from the local PDF metadata — for
arxiv-named PDFs that means `authors` may be `[]` if the PDF's `/Author`
field is empty, and `abstract_for_rag` will derive from the body text rather
than the official arxiv abstract. No `arxiv lookup ...` warnings appear on
stderr regardless of network availability.

### `--save-images`

Save images extracted from PDFs to `<output>/images/<source_stem>/imgN.png`
and reference them from the body. Implies `--high-fidelity`.

**Use this when** the images are part of the document's content (architecture
diagrams, figures referenced by ID in the prose) and downstream consumers can
display them.

**Don't use this when** images are decorative, or your retrieval pipeline
doesn't render images — the default caption-only mode produces smaller output.

```bash
any2md --save-images architecture.pdf
```

You'll see an `images/` subdirectory created under your output directory and
`![figure](images/architecture/img1.png)`-style references in the body.

## Frontmatter overrides

Frontmatter fields can be set from three sources, with the highest priority
last: auto-discovered `.any2md.toml`, `--meta-file`, then `--meta KEY=VAL`
arguments. See [output-format.md](output-format.md) for the field reference
that defines what each key means.

### `--auto-id`

Generate an SSRM-conformant `document_id` of the form
`{PREFIX}-{YYYY}-{TYPE}-{SHA8}`. Defaults: `PREFIX=LOCAL`, `TYPE=DOC`. Override
via `[document_id]` in `.any2md.toml` (`publisher_prefix`, `type_code`).

**Use this when** your retrieval pipeline keys on `document_id` and you don't
have stable IDs from elsewhere — auto-generated IDs derive from the body hash,
so they're stable across re-conversions and unique per body.

**Don't use this when** you already have authoritative document IDs in another
system. Set `--meta document_id=<your-id>` to use those values instead, so the
two systems agree.

```bash
any2md --auto-id paper.pdf
```

You'll see `document_id: "LOCAL-2026-DOC-a3f1c91d"` in the frontmatter — the
SHA8 is the first 8 hex chars of `content_hash`.

### `--meta KEY=VAL`

Set or override a frontmatter field. Repeatable. Comma-separated values become
arrays. Dotted keys set nested fields.

**Use this when** you have ad-hoc, per-invocation overrides — a one-off
attribution, a flag from a build script, or a quick test of how a frontmatter
field affects downstream processing.

**Don't use this when** the same overrides apply to every conversion in a
project. Use `.any2md.toml` so the values live with the corpus rather than in
shell history.

```bash
any2md --meta organization=OWASP \
       --meta authors="Alice, Bob" \
       --meta generation_metadata.authored_by=human \
       paper.pdf
```

You'll see those values in the frontmatter, replacing whatever was auto-derived
or empty.

### `--meta-file PATH`

Load TOML defaults from `PATH`. CLI `--meta` arguments still override values
from the file.

**Use this when** you have multiple corpora with different defaults and want
to keep their config files distinct from the auto-discovered `.any2md.toml`.

**Don't use this when** you only have one config — drop a `.any2md.toml` at
the corpus root and let auto-discovery find it.

```bash
any2md --meta-file ./corpus-defaults.toml ./corpus
```

You'll see frontmatter with all keys from `[meta]` in the TOML file, plus any
`[document_id]` overrides applied to `--auto-id` outputs.

### `.any2md.toml` (auto-discovery)

When neither `--meta-file` nor `--meta` is sufficient, drop a `.any2md.toml`
at or above the working directory. any2md walks up from the cwd until it
finds one. Example:

```toml
[meta]
organization = "Cloud Security Alliance"
document_type = "guidance"
content_domain = ["ai_security"]

[meta.generation_metadata]
authored_by = "human_ai_collaborative"

[document_id]
publisher_prefix = "CSA"
type_code = "GD"
```

With this file at `./corpus/.any2md.toml` and the cwd inside `./corpus/`, every
conversion picks up the defaults automatically. There's no flag to enable or
disable auto-discovery — drop the file and it's active.

## Body-level transformations

### `--profile {conservative,aggressive,maximum}`

Tune how aggressively the post-processing pipeline minimizes the body.

**Default:** `aggressive`.

| Profile | Stages skipped | When to use |
|---|---|---|
| `conservative` | T4 (TOC dedupe), C6 (footnote-marker strip) | Maximum fidelity to the source; you'd rather keep redundant TOC text than risk false positives. |
| `aggressive` | none | Default. Lossless minimization for RAG ingestion. |
| `maximum` | none, **and implies `--strip-links`** | Most compact output. Drops link URLs from the body. |

**Use `conservative` when** you're producing reference-quality archival output and the small token wins are not worth the small risk of a false positive on the TOC heuristic.

**Use `aggressive` (default) when** you want the standard RAG-optimized output.

**Use `maximum` when** token budget is the dominant constraint and you've confirmed the URL stripping is safe for your downstream consumers.

```bash
# Default: aggressive
any2md report.pdf

# Maximum compaction
any2md --profile maximum report.pdf
```

### `--strip-links`

Remove markdown links from the body, keeping only the link text.

**Use this when** the link URLs are noise for retrieval (long tracking URLs,
intra-document anchors, footnote backrefs) and you want to minimize tokens.

**Don't use this when** URLs in the source are part of the content — citation
URIs in academic PDFs, references to external standards, anything where the
URL itself is what's being retrieved.

Before:
```markdown
See [the spec](https://example.com/spec/v1#section-3) for details.
```

After (with `--strip-links`):
```markdown
See the spec for details.
```

```bash
any2md --strip-links paper.pdf
```

## Validation and verbosity

### `--strict`

Promote pipeline validation warnings to errors. The CLI exits with code 3
when at least one warning was emitted (and no hard failure occurred).

**Use this when** you want a CI gate that fails on conversion problems —
heading-hierarchy auto-fixes, missing H1, `content_hash` round-trip mismatches,
duplicate-paragraph removal.

**Don't use this when** you're iterating interactively and want warnings as
information rather than failures. The default behavior already prints them.

```bash
any2md --strict ./corpus
```

You'll see the same `OK:` lines as without the flag, but the exit code will
be `3` if any file produced warnings. Combine with `set -e` in shell scripts
or with CI gates that key on exit code.

### `--quiet`, `-q`

Suppress per-file `OK:` lines. Errors and the final summary still print.

**Use this when** you're running over a large corpus and per-file lines flood
the log. CI logs are the canonical use case.

**Don't use this when** you're investigating a specific file's conversion —
the `OK:` line carries the backend, lane, word count, and warning count, all
of which help diagnosis.

```bash
any2md -q ./corpus
```

You'll see only the final `Done in …` summary.

### `--verbose`, `-v`

Print pipeline stage timings per file.

**Use this when** you're investigating a slow conversion or comparing backend
performance — `--verbose` shows where time is spent across the per-stage
pipeline.

**Don't use this when** the corpus is large and you only need aggregate
performance — the per-file timing detail is not useful in bulk.

```bash
any2md -v report.pdf
```

You'll see additional lines per file showing how long each pipeline stage
took.

## Help

### `--help`, `-h`

Print the argparse-generated help and exit.

**Use this when** you want a flag list without consulting documentation.

**Don't use this when** you need detail beyond the one-line argparse help —
this document, [output-format.md](output-format.md), and
[architecture.md](architecture.md) carry the full reference.

```bash
any2md --help
```

## Exit codes

| Code | Meaning |
|---|---|
| `0` | All files converted, no failures. Warnings may have been logged. |
| `1` | Usage error or pre-flight failure (unknown flag, missing required argument, `-H` requested without Docling installed, malformed `--meta`, missing `--meta-file`). |
| `2` | At least one file failed entirely during conversion. |
| `3` | At least one file produced warnings and `--strict` was set, with no hard failures. |

`--strict` and a hard failure are mutually exclusive in the exit code: a hard
failure produces `2`, even if other files also produced warnings. The full
warning list is on stderr.

`argparse` itself emits exit code `2` for usage errors (unknown flags). any2md
treats argparse errors as falling under the broader "usage error" category;
the test suite asserts non-zero rather than the exact `1` value for that case.

## Worked-example matrix

These map common scenarios to the exact invocation that handles them.

### Fastest turnaround on clean PDFs

```bash
any2md *.pdf
```

Default backends (pymupdf4llm if Docling absent, Docling if present), default
profile (`aggressive`), default output dir (`./Text/`). No flags. The fastest
path through any2md.

### CI-grade reproducibility

```bash
any2md -H --strict ./corpus
```

`-H` forces Docling and exits with an install hint if it's missing — the build
fails fast in environments where the high-fidelity install is required.
`--strict` turns pipeline validation warnings into a non-zero exit so the CI
gate catches heading-hierarchy issues, missing H1s, and `content_hash`
round-trip mismatches.

You'll see exit code `0` for a clean run, `1` if Docling is missing, `2` if a
file failed entirely, `3` if any warnings were emitted.

### Corporate corpus into a vector store

```bash
any2md -r --meta-file ./corpus.toml ./corpus/
```

`-r` walks the whole corpus tree. `--meta-file` applies organization-wide
defaults (organization, document_type, frameworks_referenced, default
authors). The TOML file lives next to the corpus so the configuration is
versioned alongside the source documents.

You'll see frontmatter consistent across the entire corpus, with the
publisher prefix and type code from `[document_id]` applied to any outputs
that also use `--auto-id`.

### Token-budget RAG with link minimization

```bash
any2md --strip-links ./corpus/
```

`--strip-links` removes URL noise that consumes tokens without adding
retrieval signal. Combine with `--meta-file` for organization-wide overrides
or with `--auto-id` for stable document IDs.

You'll see body output with only the visible link text — `[the spec](https://example.com)`
becomes `the spec`.

### Scanned PDFs

```bash
any2md --ocr-figures scanned.pdf
```

`--ocr-figures` implies `--high-fidelity`. Tesseract runs on each figure
region and the OCR'd text is appended to the figure caption. Slow but
self-contained.

For fully scanned PDFs (no embedded text layer at all), the better path is
[OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) before any2md:

```bash
ocrmypdf scanned.pdf scanned-ocr.pdf
any2md scanned-ocr.pdf
```

OCRmyPDF inserts a real text layer that any2md's normal extraction can read,
which is faster end-to-end than `--ocr-figures` for whole-document scans.

### Mixed inputs in one invocation

```bash
any2md doc.pdf ./html_dump/ https://example.com/article notes.txt
```

Each positional argument is classified independently. URLs go through the
SSRF-protected fetch. Directories are scanned (add `-r` to recurse).
Individual files dispatch to their format's converter. The final summary
aggregates outcomes across all four input shapes.

You'll see one `OK:` line per converted file followed by a single final
summary.

### Per-document attribution at conversion time

```bash
any2md \
  --meta organization="Internal Research" \
  --meta authors="Alice, Bob" \
  --meta generation_metadata.authored_by=human \
  paper.pdf
```

`--meta` is repeatable; values with commas become arrays; dotted keys set
nested fields. Use this for one-off conversions where you don't want to edit
a config file.

You'll see the frontmatter override the auto-derived authors/organization
values.

## Cross-references

- [README](../README.md) — orientation, install paths, usage by source type.
- [output-format.md](output-format.md) — the field reference for everything
  these flags affect.
- [architecture.md](architecture.md) — what the pipeline stages do that
  `--strict` validates and `--strip-links` modifies.
- [troubleshooting.md](troubleshooting.md) — symptom-cause-fix when an
  invocation produces unexpected output.
- [upgrading-from-0.7.md](upgrading-from-0.7.md) — flag additions vs. v0.7.
