# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] — 2026-04-26

First stable release of any2md v1.0. Validated end-to-end against
real-world documents (a 164-page PDF technical standard via Docling,
a multi-page academic DOCX, and a Wikipedia article via trafilatura).
The output contract — SSRM-compatible frontmatter, deterministic
`content_hash`, NFC + LF body normalization — is now stable. Downstream
consumers can rely on this shape.

Functional contents are identical to 1.0.0rc1; only the version is bumped.

## [1.0.0rc1] — 2026-04-26

Phase 4: configuration, polish, and the v1.0 documentation set.

### Added
- `--profile {conservative,aggressive,maximum}` flag — tunes minimization
  aggressiveness. `conservative` skips TOC dedupe and footnote-marker
  stripping; `aggressive` (default) runs the full pipeline; `maximum`
  additionally implies `--strip-links`.
- `--meta KEY=VAL` repeatable flag for frontmatter overrides. Dotted keys
  set nested fields (e.g. `--meta generation_metadata.authored_by=human`);
  comma-separated values become arrays
  (e.g. `--meta authors="Alice, Bob"`).
- `--meta-file PATH` flag plus auto-discovery of `.any2md.toml` (walks up
  from cwd). The `[meta]` table supplies frontmatter overrides; the
  `[document_id]` table supplies `--auto-id` prefix and type code.
- `--auto-id` flag — generates an SSRM-conformant `document_id` as
  `{PREFIX}-{YYYY}-{TYPE}-{SHA8}`. Defaults to `LOCAL`/`DOC`; override via
  the `[document_id]` table in `.any2md.toml`.
- `--strict` flag — promotes pipeline validation warnings (heading
  hierarchy auto-fixes, missing H1, `content_hash` round-trip mismatches)
  to a non-zero exit.
- `--quiet` / `-q` flag — suppresses the per-file `OK:` lines. Errors and
  the final summary still print.
- `--verbose` / `-v` flag — adds per-file pipeline stage timings.
- New exit code contract: `0` success, `1` usage or install error, `2` at
  least one file failed entirely, `3` at least one file produced warnings
  AND `--strict` was set.
- Per-file summary line now includes backend, lane, token estimate, and
  warning count when present.
- New module `any2md/config.py` for `.any2md.toml` discovery and parsing
  (uses stdlib `tomllib` on 3.11+, `tomli` on 3.10).
- Comprehensive documentation set:
  - `README.md` rewritten with educational tone — every command preceded
    by why you'd run it and followed by what you'll see.
  - `docs/output-format.md` — SSRM-compatible field reference and the
    `content_hash` recomputation recipe.
  - `docs/cli-reference.md` — flag-by-flag reference with use cases and a
    worked-example matrix.
  - `docs/architecture.md` — pipeline internals, stage catalog, and
    contributor guide.
  - `docs/troubleshooting.md` — symptom-cause-fix triage guide.
  - `docs/upgrading-from-0.7.md` — migration guide.
  - `CONTRIBUTING.md` — dev setup, test commands, coding standards,
    release flow, PR process.
  - GitHub issue templates: generic bug report, conversion quality.

### Changed
- `frontmatter.compose()` now accepts an `overrides: dict | None` argument
  that deep-merges over derived fields. Used by `--meta`, `--meta-file`,
  and `.any2md.toml`.
- `cli.main()` exit-code logic refactored to track failures and
  strict-mode warnings separately, via the new
  `any2md.converters.collected_warnings()` helper.
- `--profile maximum` implies `--strip-links` automatically.

## [1.0.0a3] — 2026-04-26

Phase 3: text-lane post-processing stages and image/OCR flag wiring.

### Added
- Text-lane stages T1–T6 now active for all non-Docling output paths
  (TXT, trafilatura HTML/URL, mammoth DOCX fallback, pymupdf4llm PDF
  fallback):
  - **T1 `repair_line_wraps`** — joins soft-wrapped lines inside
    paragraphs while preserving lists, tables, code blocks, headings.
  - **T2 `dehyphenate`** — merges `co-\noperation` → `cooperation`
    when the joined word appears elsewhere in the document
    (same-doc corroboration; conservative).
  - **T3 `dedupe_paragraphs`** — drops a paragraph if it's identical to
    the immediately previous one (PDF over-extraction artifact).
  - **T4 `dedupe_toc_block`** — strips leading TOC blocks when ≥70% of
    their entries reappear as H2/H3 headings later. Aggressive/maximum
    profiles only.
  - **T5 `strip_running_headers_footers`** — removes lines that repeat
    ≥3 times across page boundaries (form-feed `\f`-aware).
  - **T6 `restore_lists_and_code`** — wraps ≥4-line indented blocks
    in fenced code.
- New CLI flags `--ocr-figures` and `--save-images`. Both imply
  `--high-fidelity`. With `--save-images`, the PDF Docling path writes
  extracted images to `<output_dir>/images/<source_stem>/imgN.png`.

### Changed
- `repair_line_wraps` runs before `dehyphenate` so hyphens that span
  joined lines are merged correctly.
- Snapshot fixtures regenerated to reflect text-lane stage output.

## [1.0.0a2] — 2026-04-26

Phase 2: Docling backend integration. PDFs and DOCX files can now be
extracted via Docling for substantially higher fidelity on multi-column
layouts and complex tables. Docling is an optional install — without it,
any2md transparently falls back to pymupdf4llm (PDF) and mammoth (DOCX).

### Added
- New optional dependency: `pip install "any2md[high-fidelity]"` installs
  Docling, which becomes the primary extraction backend for PDF and DOCX.
- `any2md/_docling.py` — detection helper plus a rate-limited install hint
  that surfaces on the stderr when an artifact-prone PDF is being converted
  without Docling installed.
- New CLI flag: `--high-fidelity` / `-H`. Forces Docling. Exits with code 1
  and prints the install hint when Docling is not present.
- `pdf_looks_complex(pdf_path)` heuristic — fast (< 50 ms) check used to
  decide whether to print the install hint when Docling is missing.
- New `PipelineOptions.high_fidelity` field (forwarded by the CLI).
- Structured-lane post-processing stages now active for Docling-emitted
  markdown:
  - **S1 `lift_figure_captions`** — converts image markdown and HTML
    `<figure>` blocks to italic `*Figure: caption*` lines. Drops image
    references (preserved with `--save-images`, planned for Phase 3).
  - **S2 `compact_tables`** — strips per-cell padding spaces in GFM tables;
    preserves alignment row intact.
  - **S3 `normalize_citations`** — coalesces `[1] [2] [3]` → `[1][2][3]`.
  - **S4 `enforce_heading_hierarchy`** — guarantees a single H1 (promotes
    first heading if needed; demotes subsequent H1s); flattens skipped
    levels (H2 → H4 becomes H2 → H3).
- Per-backend snapshot tests: PDF and DOCX now have `.docling.md` and
  `.fallback.md` golden outputs.

### Changed
- PDF and DOCX converters select backend at runtime: Docling if importable,
  pymupdf4llm/mammoth otherwise. Fallback also fires if Docling raises
  during extraction (with stderr warning).
- `extracted_via` frontmatter field reports `docling` for the new path.
- `lane` is `"structured"` for Docling output, `"text"` for fallback —
  the structured lane runs S1–S4 before shared cleanup; the text lane
  runs only shared cleanup in Phase 2 (T1–T6 land in Phase 3).

### Carried forward
- All v0.7 + v1.0.0a1 CLI flags.
- HTML/URL → trafilatura (Docling not used for web — purpose-built
  boilerplate stripping is more important than structured layout).
- TXT → heuristic `structurize()`.

## [1.0.0a1] — 2026-04-26

First prerelease of any2md v1.0. Phase 1 of 5: foundation only — no Docling
backend yet, no new CLI flags. Output frontmatter has been rewritten to be
SSRM-compatible (Structured Security Reasoning Markdown) — this is a
breaking change for downstream consumers parsing v0.7 output. See
`docs/superpowers/specs/2026-04-26-any2md-v1-design.md` for the full
v1.0 design and `docs/superpowers/plans/2026-04-26-any2md-v1-phase1-foundation.md`
for this phase's task plan.

### Added
- New `any2md/frontmatter.py` module — SSRM-compatible YAML emitter with the
  `SourceMeta` dataclass, deterministic `compute_content_hash`,
  `estimate_tokens`, `recommend_chunk_level`, `extract_abstract`, and
  `derive_title` helpers, plus the central `compose()` function (the only
  producer of the YAML block — converters never touch YAML directly).
- New `any2md/pipeline/` package with the two-lane post-processing runner
  (`structured` and `text` lanes both empty in Phase 1; filled in Phase 2/3)
  and seven shared cleanup stages C1–C7 in `pipeline/cleanup.py`:
  NFC normalization, soft-hyphen strip, ligature normalization (whitelist
  driven, NOT blanket NFKC), smart-quote/dash normalization, whitespace
  collapse, footnote-marker strip (aggressive/maximum profiles only), and
  read-only validation that emits non-fatal warnings via a contextvar.
- New `any2md/validators.py` — heading-hierarchy and `content_hash` round-trip
  checks. Used by C7 and exposed for programmatic consumers.
- pytest test suite: 86 tests covering pipeline stages, frontmatter helpers,
  content_hash determinism (including known empty-string SHA-256 vector),
  validators, all four converters end-to-end, CLI smoke tests, and
  snapshot tests for golden output.
- Synthetic test fixtures (HTML, TXT, multi-column PDF, table-heavy DOCX)
  under `tests/fixtures/docs/` — all owned, deterministic, and small.
  Generator script `tests/fixtures/make_fixtures.py` regenerates the binary
  fixtures (PDF via reportlab, DOCX via direct zip+XML — no python-docx dep).
- `[dev]` extras in `pyproject.toml`: `pytest`, `pytest-snapshot`,
  `reportlab`, `ruff`.

### Changed
- **BREAKING:** Output frontmatter shape is now SSRM-compatible. New required
  fields: `document_id` (empty string by default — opt-in via future
  `--auto-id`), `version`, `date`, `status: "draft"`, `document_type` (empty
  for non-security documents), `content_domain` (empty array),
  `authors`, `organization`, `generation_metadata.authored_by: "unknown"`,
  and `content_hash` (SHA-256 of NFC + LF body). Optional fields auto-filled
  when derivable: `keywords`, `token_estimate`, `recommended_chunk_level`,
  `abstract_for_rag` (only for documents ≥ 500 estimated tokens).
- v0.7 fields `source_file`, `source_url`, `pages`, `word_count`, and `type`
  are retained as any2md extension fields for traceability. A new
  `extracted_via` extension field records which library produced the
  markdown (`pymupdf4llm` / `mammoth+markdownify` / `trafilatura` /
  `trafilatura+bs4_fallback` / `heuristic`).
- Body is NFC-normalized with LF line endings before write — outputs are
  byte-deterministic for a given input + flag set.
- All four converters now route through the shared post-processing pipeline
  via `pipeline.run(text, lane, options)` and emit through
  `frontmatter.compose(body, meta, options)`. Converters return
  `(markdown, SourceMeta)` shape internally — they no longer touch YAML.
- DOCX metadata extraction: now reads `docProps/core.xml` and
  `docProps/app.xml` directly via `zipfile + xml.etree.ElementTree`. No
  python-docx dependency added.
- HTML converter: uses `trafilatura.bare_extraction(...)` for metadata
  (title/author/sitename/date/categories). For URL inputs, a single
  best-effort HEAD request captures HTTP `Last-Modified`.
- `.gitignore` now excludes `template/`, `test_docs/`, and `.worktrees/`.

### Carried forward unchanged
- All v0.7 CLI flags (`--input-dir`, `--output-dir`, `--force`,
  `--strip-links`, `--recursive`, `--max-file-size`, positional file/URL/dir
  arguments). The `--strip-links` flag is now wired through `PipelineOptions`.
- SSRF protection on URL fetching (private/reserved/loopback IP rejection).
- File size limits (default 100 MB).
- Filename sanitization rules.
- Skip-if-exists unless `--force`.
- pymupdf4llm, mammoth, markdownify, trafilatura, BeautifulSoup, lxml
  backends.
- Python 3.10+ floor.

### Out of scope for Phase 1
Phase 2 (Docling backend, `--high-fidelity`, structured-lane stages S1–S4),
Phase 3 (figure/OCR handling, text-lane stages T1–T6, full metadata
extraction), Phase 4 (`--meta`, `.any2md.toml`, `--auto-id`, `--strict`,
`--quiet`, `--verbose`, full documentation rewrite), Phase 5 (release
validation, 1.0.0).
