# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.1.1] — 2026-05-DD

Security patch release. Closes 10 findings from a comprehensive scan
(bandit, snyk-code, gitleaks, pip-audit, trivy, manual review) plus
a 5-round adversarial review of the implementation plan.

### Security

- **SSRF intra-hop DNS-rebind**: `safe_fetch` now resolves the
  hostname once, validates the IP against an allowlist, and passes
  the validated IP through to `socket.create_connection` via a
  custom `HTTPSConnection`. Defeats attacks that return a public IP
  to a validator and a private IP (e.g., `169.254.169.254`) to the
  connector. `ProxyHandler({})` explicitly suppresses
  `HTTP_PROXY`/`HTTPS_PROXY` env vars that would otherwise route
  traffic past the validator.
- **IP allowlist**: switched from a four-flag denylist
  (`is_private | is_reserved | is_loopback | is_link_local`) to an
  allowlist (`is_global and not is_multicast and not is_unspecified`).
  **Breaking** for users on multicast / CGNAT / IETF-reserved
  networks fetching same-network resources; pre-fetch with `curl`
  and pass `--from-file` as a workaround.
- **Frontmatter override-key validation**: keys must now match
  `^[A-Za-z_][A-Za-z0-9_-]*$`. Defends against newline-injection in
  TOML basic-string keys that produced split YAML lines.
  **Breaking** for TOML configs with quoted keys containing
  whitespace or punctuation.
- **URL credentials and sensitive query parameters** in `userinfo`
  and matching `(?i)(token|api[_-]?key|access[_-]?token|bearer|signature|sig|password|secret|aws[_-]?session[_-]?token)$`
  are scrubbed before any logging, persistence, or filename
  derivation. IPv6 host brackets preserved across the scrub.
- **Docling image saves** use `O_EXCL|O_NOFOLLOW` to refuse symlink
  TOCTOU.
- **`atomic_write_text`** tightens the symlink-check window via
  `os.lstat` immediately before `os.replace`. Parent-dir hardening
  deferred to v1.2 per the operator-trusted threat model.
- **Stderr/stdout sanitizer** extended with Unicode bidi
  (U+202A–E, U+2066–9), zero-width chars (U+200B–F, U+FEFF), and
  the BOM. New `any2md._logging` module; `_sanitize_log_text`
  re-exported from `any2md.converters.docx` for one release.
- **`publish.yml` workflow**: top-level `permissions: contents: read`;
  both publish jobs flip to `attestations: true` for PEP 740 sigstore
  provenance.

### Fixed

- `wikipedia.org` heuristic host check no longer matches
  `evilwikipedia.org`. Pure correctness fix; impact was incorrect
  text formatting only, not a security boundary.
- `_USER_AGENT` no longer hardcoded to `any2md/1.0.6`; derives from
  `__version__`.

### Changed

- `requirements.txt` is now a generated artifact; canonical source
  is `.devcontainer/requirements.lock` with hashes
  (`--require-hashes` enforced in `.devcontainer/devcontainer.json`).
  See `CONTRIBUTING.md` for the dep-update workflow.
- `load_toml()` now warns to stderr on parse error rather than
  silently returning `{}`.
- `.devcontainer/` is now tracked in git (was previously ignored)
  so the security-critical Codespace bootstrap config is
  version-controlled.

## [1.1.0] — 2026-05-04

Performance and library-mode hygiene release.

### Added

- `any2md.release_models()` — imperative escape hatch to free
  cached Docling `DocumentConverter` instances. Stability:
  experimental for v1.1.0.
- `any2md.docling_session()` — contextmanager (preferred shape
  for library use). Stability: experimental for v1.1.0.
- `ANY2MD_DOCLING_CACHE=0` env-var to disable the persistent
  converter cache (per-call construction, equivalent to v1.0.x
  behavior).
- `__all__` declared on `any2md/__init__.py` (formalizes the
  public surface).
- New benchmark `scripts/bench_docling_cache.py` for maintainer
  pre-release verification.

### Changed

- `DocumentConverter` is now constructed once per process and
  reused across all files in a batch (was: once per file). New
  one-time stderr line `Loading Docling models (one-time)...`
  printed on first PDF/DOCX in non-quiet TTY runs.
- `.github/workflows/ci.yml` now runs `pytest tests/unit` on each
  push and PR (was: lint + import smoke + pip-audit only).

### Performance

- Measured: CPU first-call ~2.47s (model load), warm calls ~0.87s
  (vs prior ~2.47s per file in v1.0.x). Mac MPS first-call ~2.77s,
  warm ~0.14s. RSS floor +535 MB sustained for the process lifetime
  (see `docs/troubleshooting.md` for `release_models()` mitigation).

### Migration

- None required for CLI users. The `Loading Docling models...`
  stderr line is the only user-visible default-output change.
- Library/embedder users holding any2md across long-running
  processes should call `any2md.release_models()` or use
  `with any2md.docling_session():` to free model state between
  workloads.
- Test/instrumentation code that monkey-patches
  `docling.document_converter.DocumentConverter` AFTER any2md's
  first call will see no effect on subsequent calls (cache returns
  the pre-patch instance). Workaround: call `release_models()`
  after applying the patch, or set `ANY2MD_DOCLING_CACHE=0` in the
  test environment.

### Stability notice

The new public APIs (`release_models`, `docling_session`) are
marked experimental for v1.1.0; their shape may change in
subsequent v1.x releases without a major bump until promoted to
stable in a later release.

### Known limitations

- HF Hub outages during cold-start now cause N retries instead of
  one silent fallback (the v1.0.x failure-cache behavior was
  rejected on quality grounds). Bounded retry-with-backoff
  deferred to a future hardening PR.
- Forking a process (`multiprocessing` with `fork` start method)
  after the first `convert()` call inherits torch/CUDA state
  unsafely regardless of cache. Use
  `multiprocessing.set_start_method("spawn")` or call
  `release_models()` before fork.
- `os.register_at_fork` is POSIX-only; on Windows the fork-reset
  path is dead code (no fork on Windows). Cache works normally
  on Windows.

## [1.0.7] — 2026-04-29

Branding/rebrand release. The frontmatter contract that any2md emits is
now described as "SAGE-compatible" (Security Analysis and Guidance
Exchange) — the upstream specification was renamed from SSRM (Structured
Security Reasoning Markdown) to SAGE. No functional or schema changes:
field names, ordering, controlled vocabularies, and `content_hash`
derivation are byte-identical to v1.0.6. Existing v1.0.6 outputs remain
valid SAGE-compatible documents without modification.

### Changed

- README, CHANGELOG, and all of `docs/` updated to reference SAGE /
  Security Analysis and Guidance Exchange.
- `--auto-id` CLI help text now reads "SAGE-conformant document_id"
  (previously "SSRM-conformant"). Behavior unchanged.
- Module/function docstrings in `any2md/frontmatter.py`,
  `any2md/converters/txt.py`, and `any2md/pipeline/cleanup.py` updated
  to reference SAGE §3 / §5.1 (same section numbers as the upstream
  SSRM v1.0-RC1 spec).
- Two test functions renamed for naming consistency
  (`test_txt_end_to_end_writes_sage_compat_output`,
  `test_compose_emits_required_sage_fields`). Pytest auto-discovery is
  unaffected; assertions unchanged.

### Migration

None required. Public API, CLI flags, frontmatter shape, and
`content_hash` outputs are all preserved bit-for-bit.

## [1.0.6] — 2026-04-27

Security hardening release. Closes 8 actionable findings from the
2026-04-27 multi-tool audit (semgrep + trivy + gitleaks + bandit +
pip-audit + manual review by the security-engineer agent + Opus 4.7).
No public API changes; behavior unchanged for legitimate inputs.

### Security

- **F1 (HIGH)** SSRF: replaced `trafilatura.fetch_url` and the bare
  `urllib.request.urlopen` paths with a new `any2md/_http.py` module
  that does manual redirect walking with per-hop revalidation. Defends
  against DNS-rebinding and redirect-based bypass of the IP-class
  check. New `validate_url` rejects non-http(s) schemes and
  private/loopback/link-local/reserved targets. 20 MB body cap, 3-hop
  redirect cap, redirect-loop detection. Applied to `convert_url`,
  `_http_last_modified`, and `arxiv_lookup`.
- **F5 (MED)** `--meta` integrity: `content_hash`, `extracted_via`,
  `source_file`, `lane`, `token_estimate`, `recommended_chunk_level`
  are now **reserved** and silently filtered from `--meta` /
  `--meta-file` / `.any2md.toml` overrides with a stderr `WARN` per
  drop. Defense-in-depth filter also runs inside `frontmatter.compose`.
- **F3 (MED)** TOML auto-discovery now stops at the first ancestor
  containing `.git` / `pyproject.toml` / `setup.py` / `setup.cfg` /
  `package.json` / `.any2md.toml.boundary`. New `--no-config` flag
  fully disables discovery.
- **F4 (MED)** DOCX zip-bomb: `_safe_zip_open` enforces a 1 MB cap on
  the declared uncompressed size of `core.xml` and `app.xml` before
  parsing. Oversized members raise `ValueError` → clean per-file FAIL.
- **F-CVE (MED)** Dependency floors bumped: `lxml>=6.1.0,<7`
  (CVE-2026-41066), `pillow>=12.2.0,<13` (CVE-2026-25990,
  CVE-2026-40192), `urllib3>=2.6.3,<3` (CVE-2026-21441). All ranges
  acquire upper bounds (compat envelope). `requirements.txt` becomes
  a development/CI lockfile with exact pins.
- **F6 (LOW)** Atomic writes: new `any2md.utils.atomic_write_text`
  writes via `tempfile.mkstemp` + `os.replace`. Refuses to overwrite
  a pre-existing symlink at the output path. Wired through
  `pdf/docx/html/txt` converters; PDF image extraction adds a symlink
  check before `pil_image.save`.
- **F2 (LOW)** Control-char sanitizer strips C0/C1 controls (preserves
  `\t`, `\n`) from captured Docling `msword_backend` warnings before
  forwarding them to `collected_warnings()` and stderr. Defends
  terminals from ANSI-escape spoofing.
- **F11 (LOW)** PDF image-dir name now goes through `safe_dir_name`
  (alphanumeric/`_`/`-` only). Closes a `Path.stem == ".."` corner
  case that co-mingled images with markdown outputs.
- **XXE defense-in-depth**: migrated `xml.etree.ElementTree` →
  `defusedxml.ElementTree` in `docx.py` and `heuristics.py`. Stdlib
  was already safe in Python 3.7+; this silences bandit B405/B314
  permanently and protects against future stdlib regressions.

### Added

- New module `any2md/_http.py` (`validate_url`, `safe_fetch`).
- New CLI flag `--no-config`.
- New helpers `any2md.utils.atomic_write_text` and `safe_dir_name`.
- New runtime dependency: `defusedxml>=0.7.1,<1`.

### Tests

- 7 new unit-test files (40 new tests): `test_http_safe.py`,
  `test_meta_reserved_keys.py`, `test_config_walkup.py`,
  `test_zipbomb_guard.py`, `test_atomic_write.py`,
  `test_safe_dir_name.py`, `test_log_sanitizer.py`.
- Existing 290 tests continue to pass.
- Bandit audit went from **9 findings** (3 medium, 6 low) to **1 low**
  (legitimate `try/except/pass` in arxiv `_warn`).
- 5-DOCX regression run reproduces v1.0.5 word counts exactly
  (978/6726/15566/7811/1477).

### Audit summary

| ID | Title | Severity |
|----|-------|----------|
| F1 | SSRF: DNS rebind + redirect bypass | High |
| F5 | `--meta` clobbers reserved frontmatter | Medium |
| F3 | TOML discovery walks above project root | Medium |
| F4 | DOCX zip-bomb amplification | Medium |
| F-CVE | Transitive deps with known CVEs | Medium |
| F6 | Symlink-following on output writes | Low |
| F2 | Control-char passthrough in Docling logs | Low |
| F11 | PDF stem `..` corner case | Low |

## [1.0.5] — 2026-04-27

Patch release. Recovers DOCX content that Docling's msword backend
silently drops on malformed list structures, by auto-retrying
affected files through the mammoth lane and forwarding the
captured Docling warnings into any2md's run-level warning bucket.
Real-world impact observed during validation: a 12,740-word
Docling output for a policy-template DOCX recovered to 15,566
words (+22%) when re-rendered via mammoth.

### Added
- DOCX converter now auto-retries files through the mammoth lane
  when Docling emits any warning from
  `docling.backend.msword_backend` during conversion. Docling's
  DOCX backend silently drops list items in a known
  malformed-input path (`msword_backend.py:1377/1675` —
  "Parent element of the list item is not a ListGroup. The list
  item will be ignored."), so a warning means the Docling
  Markdown is missing content. On fallback, `extracted_via` is
  set to `"docling→mammoth (warning fallback)"`, the lane
  switches to `text`, the captured Docling warnings are
  forwarded into the run-level warning bucket (so `--strict`
  still fails), and a `FALLBACK:` line is printed to stderr.
  Default: enabled. Disable with `--no-docx-fallback-on-warn`
  (e.g. when comparing backends explicitly).
- New `PipelineOptions.docx_fallback_on_warn: bool = True`.
- New CLI flag pair `--docx-fallback-on-warn` /
  `--no-docx-fallback-on-warn`.

### Tests
- New `tests/integration/test_docx_fallback_on_warn.py` covers
  the warning-capture context manager, the default-on fallback
  path (output swap, `extracted_via`, captured warning forwarded
  into `collected_warnings()`, user-visible message), the
  `--no-docx-fallback-on-warn` opt-out, the no-warning
  fast-path, and the explicit `--backend docling` interaction.

## [1.0.4] — 2026-04-26

Patch release. Two follow-ups deferred from v1.0.3 (#17): the T7
`dedupe_toc_table` now normalizes leader-dot padding from TOC
cells before matching against body headings, so Docling-rendered
TOC tables (e.g., `Purpose..........Page`) get properly stripped;
and the audit script's `leading-toc-table` check no longer
false-flags documents whose only GFM table sits at the end (skip
when the body contains no H2).

### Changed
- `pipeline/text.py::dedupe_toc_table` strips leader-dot padding
  (`re.sub(r'\.{3,}.*$', '', cell)`) from each TOC cell before
  lower-casing and matching against body H2/H3 titles. (The
  text-block TOC variant already handles this via `_TOC_LINE_RE`'s
  capture group — only the table-variant site needed the fix.)
- `scripts/audit-outputs.py` `leading-toc-table` check is now
  gated on `"\n## "` being present in the body — when no H2
  exists, no "leading-TOC region" is defined, so the check is
  skipped instead of matching the entire document.

### Fixes
- TOC tables with dotted-page-number padding (typical Docling
  output for SafeBreach-style PDFs — e.g., `Backup.pdf`,
  `Password.pdf`) now get stripped by T7 in aggressive/maximum
  profiles. Previously they survived because the cell content
  `"1.1. Purpose............."` failed string-equality with the
  body heading `"1.1. Purpose"`, dropping overlap below the 70%
  threshold.
- Audit script no longer reports false-positive
  `leading-toc-table` flags on documents whose only GFM table is
  at the end and the body contains no `## ` headings.

### Tests
- New `test_strips_toc_table_with_leader_dot_padding` in
  `tests/unit/pipeline/test_text_dedupe_toc_table.py` — TOC
  table whose cells carry leader-dot padding mirroring later H2
  headings still triggers the strip.
- New `tests/unit/scripts/test_audit_outputs.py` covering the
  audit-script `leading-toc-table` check: no-H2-with-trailing-
  table is NOT flagged; leading-table-before-H2 IS still flagged.

### Other
- `scripts/audit-outputs.py` is now tracked in version control
  (was previously local-only).

## [1.0.3] — 2026-04-26

Patch release. Audit on the v1.0.2-regenerated corpus surfaced two
patterns the previous release did not handle: cover-page-titled
documents whose first H2 stripped to empty produced an empty
`title` field, and Docling-lane output retained malformed `|`
table-row remnants because the lone-punctuation filter was
text-lane-only. The lane-agnostic body cleanup that v1.0.2's
text lane already had also now runs on Docling output.

### Added
- New lane-agnostic stage **`strip_orphan_punctuation`** — drops
  lines containing only `|` or `>`. Extracted from T10
  `strip_web_fragments` so it can run on the structured (Docling)
  lane in addition to the text (trafilatura) lane.

### Changed
- `heuristics.refine_title` now walks all H2 lines line-by-line
  and skips any whose content strips to empty after removing
  markdown emphasis, instead of always returning the first
  regex match. Also guards the Wikipedia-prefix strip against
  emitting empty when the candidate is the bare prefix.
- `pipeline/structured.py` now extends `STAGES` with
  `strip_repeated_byline` (T9), `dedupe_toc_table` (T7),
  `strip_cover_artifacts` (T8), and `strip_orphan_punctuation`
  so Docling output gets the same body-cleanup pass as text-lane
  output. T10's short-fragment heuristic stays text-lane-only —
  it would over-strip Docling's deliberate short headings.
- `pipeline/cleanup.py` `decode_html_entities` (C8) now loops
  `html.unescape` until output stabilizes (max 5 iterations) so
  double-encoded entities like `&amp;amp;` → `&amp;` → `&` are
  fully decoded. Some extractors emit doubly-encoded entities
  that survived a single pass.

### Fixes
- **Empty-title regression**: cover-page H1 documents whose first
  H2 contained only markdown emphasis, NBSP-equivalent unicode,
  or where the H2 regex's `\s+` class spanned a newline into the
  next paragraph produced `title: ""`. Walk H2 lines line-by-line
  with a non-empty guard.
- **Orphan-punctuation in Docling output**: malformed table-row
  remnants (lone `|`) survived in structured-lane output because
  T10 was text-lane-only. New `strip_orphan_punctuation` runs on
  both lanes.
- **Double-encoded HTML entities**: `&amp;amp;` left a residual
  `&amp;` after a single unescape pass. Loop until stable.

### Tests
- 4 new tests in `tests/unit/test_heuristics.py::TestRefineTitle`
  covering NBSP-only H2, emphasis-only H2 (skip-and-pick-next),
  all-empty-H2 fallthrough, and Wikipedia-prefix-only candidate.
- New `tests/unit/pipeline/test_strip_orphan_punctuation.py`
  covering aggressive removal, conservative no-op, and preservation
  of lines containing other content alongside `|`/`>`.
- New `tests/unit/pipeline/test_structured_body_cleanup_stages.py`
  asserting the lane-agnostic stages are registered and that the
  targeted patterns are removed from structured-lane output.
- New `tests/unit/pipeline/test_cleanup_html_entities_double_encoded.py`
  covering the C8 loop.

## [1.0.2] — 2026-04-26

Patch release. Closes issue #15 plus 8 additional quality issues
discovered during deep investigation against four real-world inputs:
arxiv academic paper, ISO/IEC 27002 standard, COMP4441 academic
DOCX, and a Wikipedia article via URL.

### Added
- New `any2md/heuristics.py` module — pure functions for frontmatter
  field refinement: `refine_title`, `refine_abstract`, `extract_authors`,
  `filter_organization`, `arxiv_lookup`, `is_arxiv_filename`. Called
  from `frontmatter.compose()` and from converter modules.
- New `produced_by` extension field on `SourceMeta` and frontmatter
  (between `extracted_via` and `pages`). Records the software that
  produced the source file (PDF `Creator`, DOCX `Application`).
  Distinct from `extracted_via` which records the any2md backend
  that produced the markdown.
- New shared cleanup stage **C8 `decode_html_entities`** — universal
  removal of `&amp;`, `&gt;`, `&lt;`, numeric entities (`&#x2014;`,
  `&#8212;`) from body. Code-block aware (skips fenced ` ``` ` blocks).
- New text-lane stages T7-T10 (aggressive/maximum profile only):
  - **T7 `dedupe_toc_table`** — strips table-formatted TOCs that T4's
    text-formatted-TOC heuristic doesn't catch. Common in academic PDFs.
  - **T8 `strip_cover_artifacts`** — drops cover-page noise (QR-code
    blurbs, version stamps like "Third edition 2022-02") in the first
    ~30 lines, before the first H2.
  - **T9 `strip_repeated_byline`** — removes "Author's Contact
    Information:" and similar lines that duplicate a byline.
  - **T10 `strip_web_fragments`** — drops trafilatura extraction
    fragments (orphan `|` / `>` lines, short incomplete sentences
    surrounded by blank lines).
- New CLI flag `--no-arxiv-lookup` to disable the arxiv API metadata
  enrichment. Arxiv enrichment is on by default for filenames matching
  `\d{4}\.\d{4,5}` (e.g., `2501.17755v1.pdf`); SSRF-guarded with 5s
  timeout; failures emit non-blocking warnings.
- Project logo and brand assets under `assets/`.

### Fixes
The eleven quality issues — see issue #15 and
`docs/superpowers/specs/2026-04-26-any2md-v1.0.2-design.md`:
- A1: authors not extracted from PDF body byline (academic PDFs).
- A2: abstract picked the byline / cover blurb / TOC line.
- A3: organization populated with PDF Creator software junk.
- B1: HTML entities leaked to body universally.
- C1: ISO/TR titles detected as "INTERNATIONAL STANDARD" cover header.
- C3: DOCX titles concatenated course code + project title.
- C4: Wikipedia titles kept "Wikipedia:" namespace prefix.
- D1: TOCs dumped as markdown tables in academic PDFs.
- D2: trafilatura fragments leaked into web outputs.
- D3: ISO cover-page QR-code blurb leaked into body.
- E1: "Author's Contact Information:" line duplicated byline.

### Changed
- `frontmatter.compose()` now consults `heuristics.py` to refine
  title / abstract / authors before YAML emission.
- `--profile conservative` now also gates the new heuristic
  aggressiveness (skip-lists active; speculative inferences off).
- PDF `Creator` software values (LaTeX, acmart, Adobe InDesign,
  Microsoft Word, etc.) no longer populate `organization`. They
  go to the new `produced_by` field instead.

## [1.0.1] — 2026-04-26

Patch release. Adds an explicit backend-selection CLI flag.

### Added
- `--backend {docling,pymupdf4llm,mammoth}` CLI flag and corresponding
  `PipelineOptions.backend` field. Lets users override the automatic
  backend selection. Useful when Docling extracts incorrectly on a
  specific input and the user wants to fall back to pymupdf4llm
  without uninstalling Docling. Mismatched format/backend combinations
  (e.g., `--backend pymupdf4llm` on a DOCX) error out per file.

### Fixes (workaround)
- Refs #13 — Docling drops list items on certain academic PDFs with
  the "Parent element of the list item is not a ListGroup" warning.
  No upstream fix yet; users hitting this can now `any2md --backend
  pymupdf4llm doc.pdf` to use the lightweight backend instead.

### Note
- `--backend docling` is equivalent to the existing `--high-fidelity`
  / `-H` flag (both kept). Future releases may consolidate.

## [1.0.0] — 2026-04-26

First stable release of any2md v1.0. Validated end-to-end against
real-world documents (a 164-page PDF technical standard via Docling,
a multi-page academic DOCX, and a Wikipedia article via trafilatura).
The output contract — SAGE-compatible frontmatter, deterministic
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
- `--auto-id` flag — generates an SAGE-conformant `document_id` as
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
  - `docs/output-format.md` — SAGE-compatible field reference and the
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
SAGE-compatible (Security Analysis and Guidance Exchange) — this is a
breaking change for downstream consumers parsing v0.7 output. See
`docs/superpowers/specs/2026-04-26-any2md-v1-design.md` for the full
v1.0 design and `docs/superpowers/plans/2026-04-26-any2md-v1-phase1-foundation.md`
for this phase's task plan.

### Added
- New `any2md/frontmatter.py` module — SAGE-compatible YAML emitter with the
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
- **BREAKING:** Output frontmatter shape is now SAGE-compatible. New required
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
