# Upgrading from v0.7

This guide covers the migration from any2md v0.7 to v1.0. The frontmatter
shape is the only intended breaking change. The body is now NFC-normalized
with LF line endings, which is also a content change but does not break
parsers — they just see a slightly different body.

If you need v0.7's frontmatter shape exactly, pin the old release:

```bash
pip install any2md==0.7.0
```

For new orientation, see the [README](../README.md). For the v1.0 output
contract, see [output-format.md](output-format.md). For the v1.0 CLI
surface, see [cli-reference.md](cli-reference.md).

## TL;DR

- v1.0 emits **SSRM-compatible frontmatter**. The v0.7 frontmatter
  (`title`, `source_file`, `pages`, `type`, `word_count`) becomes a fuller
  block with `document_id`, `version`, `date`, `status`, `content_hash`,
  `token_estimate`, `authors`, `organization`, `generation_metadata`,
  `recommended_chunk_level`, plus a few conditional fields. The v0.7 keys
  are retained as any2md extension fields in the same block, so traceability
  is preserved.
- The body is NFC-normalized with LF line endings. `content_hash`
  (SHA-256 of NFC + LF body) is now reproducible across runs and platforms.
- New CLI flags: `--high-fidelity`, `--ocr-figures`, `--save-images`,
  `--auto-id`, `--meta`, `--meta-file`, `--strict`, `--quiet`, `--verbose`.
- New exit code contract: 0 success, 1 usage / install error, 2 file
  failure, 3 strict-mode warning.
- `pip install "any2md[high-fidelity]"` installs Docling for layout-aware
  PDF and DOCX extraction. The base `pip install any2md` keeps the v0.7-era
  pymupdf4llm + mammoth backends as the fallback path.

If you depended on the v0.7 fixed shape, pin v0.7. Otherwise, the migration
is mostly additive: existing keys keep working, new keys appear, and the
body content is normalized in ways that improve downstream determinism.

## Frontmatter field map

The table below maps v0.7 keys to v1.0 keys. v1.0 fields not present in
v0.7 are listed in the second table.

### Keys that exist in both

| v0.7 | v1.0 | Notes |
|---|---|---|
| `title` | `title` | Unchanged in semantics. v1.0 derivation is more robust: first H1, then source metadata title, then cleaned filename. |
| `source_file` | `source_file` (extension) | Retained as a non-SSRM extension field for traceability. Conditional — emitted only for file inputs, not URLs. |
| `source_url` | `source_url` (extension) | Retained as a non-SSRM extension field. Conditional — emitted only for URL inputs. |
| `pages` | `pages` (extension) | Retained as a non-SSRM extension field. PDF inputs only; absent otherwise. |
| `word_count` | `word_count` (extension) | Retained as a non-SSRM extension field. Set for DOCX, HTML, TXT; absent for PDF. |
| `type` | `type` (extension) | Retained. v1.0 values are still `pdf` / `docx` / `html` / `txt`. |

### Keys new in v1.0

| Key | Type | Notes |
|---|---|---|
| `document_id` | string | Empty by default. Filled by `--auto-id` as `LOCAL-{YYYY}-DOC-{SHA8}`. Override prefix/type via `[document_id]` in `.any2md.toml`. |
| `version` | string | Always `"1"` for v1.0. Reserved for future revisions. |
| `date` | string | ISO-8601 `YYYY-MM-DD`. Source-side metadata first, then file mtime, then today. |
| `status` | string | Always `"draft"` for converted documents. |
| `document_type` | string | Empty by default. SSRM controlled vocabulary; user-provided. |
| `content_domain` | array | Empty `[]` by default. SSRM controlled vocabulary; user-provided. |
| `authors` | array | Auto-extracted from source metadata when present. Always an array, possibly `[]`. |
| `organization` | string | Auto-extracted from source metadata when present. |
| `generation_metadata` | object | At minimum `{authored_by: "unknown"}` for converted documents. |
| `content_hash` | string | SHA-256 of NFC + LF body. 64-char lowercase hex. Always populated. |
| `token_estimate` | integer | `ceil(len(body) / 4)`. |
| `recommended_chunk_level` | string | `"h2"` or `"h3"` based on largest H2 section size. |
| `abstract_for_rag` | string | Conditional — emitted only when `token_estimate ≥ 500`. ≤ 400 chars. |
| `keywords` | array | Conditional — emitted only when at least one keyword was extracted. |
| `extracted_via` | string | Records which backend produced the markdown (`docling`, `pymupdf4llm`, `mammoth+markdownify`, `trafilatura`, `trafilatura+bs4_fallback`, `heuristic`). |
| `frameworks_referenced` | array | Empty by default. SSRM extension; user-provided via `--meta`. |
| `tlp` | string | Empty by default. SSRM marking; user-provided via `--meta`. |

For derivation rules and field semantics, see
[output-format.md](output-format.md).

## Behavior changes

### Exit codes

v0.7 used `0` for success and any non-zero value for failure without a fixed
contract. v1.0 has four documented exit codes:

| Code | Meaning |
|---|---|
| `0` | All files converted, no failures. Warnings may have been logged. |
| `1` | Usage error or pre-flight failure (unknown flag, malformed `--meta`, missing `--meta-file`, `-H` without Docling). |
| `2` | At least one file failed entirely during conversion. |
| `3` | At least one file produced warnings and `--strict` was set, with no hard failures. |

If your CI scripts checked for "exit code is 0," they continue to work. If
they checked specific non-zero values, review the new contract — `1` for
usage and `2` for runtime failure are now distinct.

### `--strict` mode

New flag. Promotes pipeline validation warnings (heading-hierarchy
auto-fixes, missing H1, paragraph dedupe, TOC dedupe, `content_hash`
round-trip mismatches) to a non-zero exit (`3`). Useful as a CI gate
against silent regressions.

```bash
any2md --strict ./corpus
```

If `--strict` exits with code 3 and you don't see an obvious problem, read
the WARN block on stderr — the warnings are descriptive. See
[troubleshooting.md](troubleshooting.md#--strict-exit-code-3-with-no-obvious-problem).

### Default backend selection

v0.7 used pymupdf4llm for all PDFs and mammoth+markdownify for all DOCX.
v1.0 keeps those backends as the **fallback** path and adds **Docling**
as the primary path when `[high-fidelity]` is installed:

| Format | v0.7 | v1.0 (Docling installed) | v1.0 (no Docling) |
|---|---|---|---|
| PDF | pymupdf4llm | Docling | pymupdf4llm |
| DOCX | mammoth+markdownify | Docling | mammoth+markdownify |
| HTML / URL | trafilatura | trafilatura | trafilatura |
| TXT | heuristic | heuristic | heuristic |

To force the Docling path (and exit with an install hint when it's not
available), pass `-H` / `--high-fidelity`. To force the v0.7-era fallback
path, simply don't install `[high-fidelity]`.

### Body normalization

v0.7 wrote the body as the backend produced it, with whatever line endings
and unicode form the input carried. v1.0 normalizes to NFC + LF before
write. This means:

- `content_hash` is reproducible across platforms.
- Soft hyphens (U+00AD) and presentation-form ligatures (`ﬁ`, `ﬂ`, etc.) are
  expanded to their letter forms.
- Smart quotes are normalized to straight quotes; ellipsis `…` to `...`.
- Inter-word whitespace runs collapse to single spaces; trailing whitespace
  per line is trimmed; runs of three or more blank lines collapse to two.

If your downstream pipeline depended on the source's original unicode form
or line endings, the v1.0 output will differ. The differences are
recoverable for individual fields (re-encoding to UTF-8 BOM, converting LF
to CRLF) but the unicode normalization is not — that's part of the
`content_hash` invariant.

### Recovering v0.7-like output

There is no flag combination that fully reproduces v0.7 frontmatter. The
new keys are part of the v1.0 contract and are always emitted. The closest
recovery path:

1. `pip install any2md==0.7.0` if you need byte-for-byte v0.7 output.
2. For body shape only, the `--profile conservative` setting (configurable
   in `.any2md.toml` or via `PipelineOptions`) skips the most aggressive
   cleanup stages (TOC dedupe T4, footnote-marker stripping C6). The
   v0.7 body shape is closest to `conservative`, though even
   `conservative` runs the lossless cleanup stages C1–C5 that v0.7 did
   not.
3. To downstream-strip the new frontmatter keys, parse the YAML, project
   onto the v0.7 key set, re-emit. This is the recommended path if you
   want v1.0's body normalization (better) plus a v0.7-shaped frontmatter
   for legacy consumers:

   ```python
   import yaml

   V07_KEYS = {"title", "source_file", "source_url", "pages",
               "type", "word_count"}

   def project_v07(md_text: str) -> str:
       parts = md_text.split("---\n", 2)
       fm = yaml.safe_load(parts[1])
       projected = {k: fm[k] for k in V07_KEYS if k in fm}
       new_fm = yaml.safe_dump(projected, sort_keys=False).rstrip()
       return f"---\n{new_fm}\n---\n{parts[2]}"
   ```

## CLI flag additions

The v0.7 flag set works unchanged in v1.0. The following flags are new:

| Flag | Purpose |
|---|---|
| `--high-fidelity`, `-H` | Force the Docling backend for PDF / DOCX. Exit 1 if Docling is not installed. |
| `--ocr-figures` | Run OCR on figures (Docling path). Implies `-H`. |
| `--save-images` | Save extracted images to `<output>/images/`. Implies `-H`. |
| `--auto-id` | Generate `document_id` as `{PREFIX}-{YYYY}-{TYPE}-{SHA8}`. |
| `--meta KEY=VAL` | Set or override a frontmatter field. Repeatable. Comma values become arrays. Dotted keys are nested. |
| `--meta-file PATH` | Load TOML defaults from `PATH`. Auto-discovery of `.any2md.toml` walks up from cwd when absent. |
| `--strict` | Promote pipeline validation warnings to errors (exit 3). |
| `--quiet`, `-q` | Suppress per-file `OK:` lines. |
| `--verbose`, `-v` | Print pipeline stage timings per file. |

Carried forward from v0.7: `--input-dir` / `-i`, `--output-dir` / `-o`,
`--force` / `-f`, `--strip-links`, `--recursive` / `-r`,
`--max-file-size`, positional file/URL/directory arguments. All of these
behave identically in v1.0.

For per-flag documentation, see [cli-reference.md](cli-reference.md).

## Migration checklist

1. **Pin or unpin.** Decide whether to pin v0.7 or migrate. If migrating,
   update your `requirements.txt` / `pyproject.toml` / lockfile to
   `any2md>=1.0`.
2. **Decide on Docling.** If your corpus has multi-column PDFs, complex
   tables, or scanned documents, install `[high-fidelity]`. Otherwise the
   base install is sufficient.
3. **Re-run a sample.** Convert one representative file with v1.0 and
   diff the frontmatter against the v0.7 output. The new keys are
   visible; existing keys are unchanged in semantics.
4. **Update downstream parsers.** If your pipeline parses frontmatter
   with a strict schema, add the new keys. If it ignores unknown keys,
   no change is needed.
5. **Add `.any2md.toml`** if you have organization-wide defaults
   (`organization`, `document_type`, `content_domain`,
   `frameworks_referenced`). Drop the file at the corpus root and any2md
   will pick it up automatically.
6. **Tighten CI.** Add `--strict` to your CI invocation so that
   pipeline validation warnings fail the build. Audit and either fix
   warnings or accept them, then keep `--strict` on going forward.

## Cross-references

- [README](../README.md) — v1.0 orientation.
- [output-format.md](output-format.md) — full v1.0 frontmatter reference.
- [cli-reference.md](cli-reference.md) — flag-by-flag reference.
- [troubleshooting.md](troubleshooting.md) — common artifacts and fixes
  after the upgrade.
- [architecture.md](architecture.md) — pipeline shape that produces the
  v1.0 output.
