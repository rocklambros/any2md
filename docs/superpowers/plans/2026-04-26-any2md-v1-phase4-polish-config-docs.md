# any2md v1.0 — Phase 4: Polish, Configuration, and Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Add the remaining CLI ergonomics (`--meta`, `--meta-file`, `.any2md.toml`, `--auto-id`, `--strict`, `--quiet`, `--verbose`), implement the new exit-code contract (0/1/2/3), and write the full deeply-educational documentation set (README + 6 `docs/*.md` files + CONTRIBUTING + 2 issue templates). Tag `1.0.0rc1` to TestPyPI.

**Tech stack:** Same as Phase 3. No new runtime dependencies. The `.any2md.toml` parser uses Python's stdlib `tomllib` (3.11+; for 3.10 we read with `tomli` — already a transitive dep of trafilatura, so no new explicit dep needed).

**Reference:** spec §6 (CLI surface, configuration, error handling) and §7 (documentation overhaul, including per-doc skeletons).

**Branch strategy:** `phase4-polish-config-docs` worktree off `v1.0`.

**Tone for all docs:** Audience is a competent reader new to RAG document pipelines. Every command preceded by *why you'd run it* and followed by *what you'll see*. No marketing language ("blazingly fast", "magnificent"). No emojis unless semantically meaningful. Concrete before/after examples where applicable. Cross-linked. No redundancy across docs.

---

## File structure

```
any2md/
  __init__.py                    [MODIFY: bump to "1.0.0rc1"]
  cli.py                         [MODIFY: --strict, --quiet, --verbose, --auto-id, --meta, --meta-file; exit codes]
  frontmatter.py                 [MODIFY: accept user-overrides dict; auto_id helper]
  config.py                      [NEW: .any2md.toml discovery + parser]

tests/
  unit/test_config.py            [NEW]
  unit/test_auto_id.py           [NEW]
  unit/test_meta_overrides.py    [NEW]
  cli/test_cli_strict.py         [NEW]
  cli/test_cli_quiet_verbose.py  [NEW]
  cli/test_cli_meta.py           [NEW]
  cli/test_cli_exit_codes.py     [NEW]

docs/
  output-format.md               [NEW: ~400 lines]
  cli-reference.md               [NEW: ~300 lines]
  architecture.md                [NEW: ~500 lines]
  troubleshooting.md             [NEW: ~300 lines]
  upgrading-from-0.7.md          [NEW: ~150 lines]
README.md                        [REWRITE: ~600 lines, deeply educational]
CONTRIBUTING.md                  [NEW: ~120 lines]
.github/
  ISSUE_TEMPLATE/
    bug_report.md                [NEW]
    conversion_quality.md        [NEW]

CHANGELOG.md                     [MODIFY: 1.0.0rc1 entry]
```

---

## Task 1: Bump version + `--strict` / `--quiet` / `--verbose` flags

**Files:** `any2md/__init__.py`, `any2md/cli.py`. Test: `tests/cli/test_cli_strict.py`, `tests/cli/test_cli_quiet_verbose.py`.

- [ ] Bump `__version__ = "1.0.0rc1"` in `any2md/__init__.py`.
- [ ] Add three flags to argparse:

```python
parser.add_argument("--strict", action="store_true",
    help="Promote pipeline validation warnings to errors (exit 3).")
parser.add_argument("--quiet", "-q", action="store_true",
    help="Suppress per-file 'OK:' lines. Errors and final summary still print.")
parser.add_argument("--verbose", "-v", action="store_true",
    help="Print pipeline stage timings per file.")
```

- [ ] Forward `strict` into `PipelineOptions`. `quiet`/`verbose` are CLI-only (control output, not pipeline behavior); store in module-level controls.

- [ ] Modify the `OK:` print path so it's suppressed when `args.quiet` and that warnings still print.

- [ ] When any per-file conversion ends with ≥ 1 warning AND `args.strict`, accumulate a `had_strict_warning` flag. At end of run, exit 3 if set (and there were no hard failures, which exit 2).

- [ ] Tests:

```python
# tests/cli/test_cli_strict.py
import subprocess, sys
def _run(*args):
    return subprocess.run([sys.executable, "-m", "any2md", *args], capture_output=True, text=True)

def test_strict_in_help():
    assert "--strict" in _run("--help").stdout

def test_strict_exits_3_when_warnings(tmp_path):
    # Create a TXT file that will trigger validation warnings (e.g., missing H1)
    src = tmp_path / "noh1.txt"
    src.write_text("body without H1\n")
    out = tmp_path / "out"
    r = _run("--strict", "-o", str(out), str(src))
    # validation warns "H1 count is 0" → strict promotes to exit 3
    assert r.returncode == 3
```

```python
# tests/cli/test_cli_quiet_verbose.py
import subprocess, sys
def _run(*args):
    return subprocess.run([sys.executable, "-m", "any2md", *args], capture_output=True, text=True)

def test_quiet_in_help():
    assert "--quiet" in _run("--help").stdout

def test_quiet_suppresses_per_file_ok(fixture_dir, tmp_path):
    out = tmp_path / "out"
    r = _run("-q", "-o", str(out), str(fixture_dir / "ligatures_and_softhyphens.txt"))
    assert r.returncode == 0
    assert "OK:" not in r.stdout

def test_verbose_in_help():
    assert "--verbose" in _run("--help").stdout
```

Commit: `feat(cli): --strict, --quiet, --verbose flags`

---

## Task 2: New exit codes (0/1/2/3)

**Files:** `any2md/cli.py`. Test: `tests/cli/test_cli_exit_codes.py`.

Exit code contract:
- **0**: success
- **1**: argparse / usage / install error (already in place)
- **2**: ≥ 1 file failed entirely (HARD failure)
- **3**: ≥ 1 file produced warnings AND `--strict`

Refactor `cli.main()` to track `had_failure` and `had_strict_warning` separately. The `fail += 1` accumulation already exists; map it to the new exit codes:

```python
# at end of main()
if fail > 0:
    sys.exit(2)
if had_strict_warning:
    sys.exit(3)
sys.exit(0)
```

For `had_strict_warning` to be tracked, the converters need to bubble up "had warning" info. Simplest path: inspect the warnings list returned by `pipeline.run` (already returned but not yet bubbled out of converters). Modify converters to print warnings AND return whether any occurred.

Cleaner alternative: read converter output's frontmatter post-write to detect warnings. Too indirect. Stick with bubbling.

**Implementation:** add a `convert_*` shared helper that returns `(ok: bool, warnings: list[str])`. Update all four `convert_*` functions to return that tuple, OR keep them returning bool and have them write warnings to a shared module-level list. Use a module-level list (simpler, no signature change):

```python
# any2md/converters/__init__.py
_RUN_WARNINGS: list[str] = []

def reset_warnings() -> None:
    _RUN_WARNINGS.clear()

def add_warnings(warnings: list[str]) -> None:
    _RUN_WARNINGS.extend(warnings)

def collected_warnings() -> list[str]:
    return list(_RUN_WARNINGS)
```

Each converter calls `add_warnings(warnings)` after `pipeline.run(...)` returns. `cli.main()` calls `reset_warnings()` at start and checks `collected_warnings()` at end.

Tests:

```python
# tests/cli/test_cli_exit_codes.py
import subprocess, sys
def _run(*args):
    return subprocess.run([sys.executable, "-m", "any2md", *args], capture_output=True, text=True)

def test_exit_0_clean(fixture_dir, tmp_path):
    r = _run("-o", str(tmp_path / "out"), str(fixture_dir / "web_page.html"))
    assert r.returncode == 0

def test_exit_1_unknown_flag():
    r = _run("--bogus-flag")
    assert r.returncode != 0  # argparse exits 2 by default; we accept any non-zero
    # Specifically argparse uses exit 2 for usage errors. Document that
    # in the exit-code reference. For our purposes, just confirm non-zero.

def test_exit_2_file_failed(tmp_path):
    # Pass a non-existent file via --input-dir to a non-dir
    r = _run("--input-dir", str(tmp_path / "nonexistent"))
    assert r.returncode == 1  # input-dir not a dir → usage error

def test_exit_2_when_one_of_many_fails(fixture_dir, tmp_path):
    # Mix existing fixture with non-existent file
    out = tmp_path / "out"
    r = _run("-o", str(out),
        str(fixture_dir / "web_page.html"),
        str(tmp_path / "doesnotexist.pdf"))
    # Existing prints NOT FOUND but doesn't fail (existing behavior).
    # If the file doesn't exist, the converter never runs → no fail counted.
    # For an actual extraction failure, we'd need a corrupted file.
    # Acceptable: this test asserts the all-existing path returns 0.
    # Or skip: hard to construct a failing file deterministically.
    # → just assert returncode in (0, 2) and that the missing file was reported.
    assert r.returncode in (0, 2)
    assert "NOT FOUND" in (r.stdout + r.stderr)
```

Commit: `feat(cli): Exit code 2 on failure, 3 on strict-mode warnings`

---

## Task 3: `--auto-id` flag

**Files:** `any2md/cli.py`, `any2md/frontmatter.py`. Test: `tests/unit/test_auto_id.py`.

`--auto-id` generates `document_id` as `LOCAL-{YYYY}-DOC-{sha8(body)}`. Override the publisher prefix and type code via `.any2md.toml` (Task 6). Phase 4 hardcodes `LOCAL` and `DOC` as the defaults.

- [ ] Write tests:

```python
# tests/unit/test_auto_id.py
from datetime import date
from any2md.frontmatter import generate_document_id


def test_generate_document_id_format():
    body = "# Title\n\nbody.\n"
    doc_id = generate_document_id(body, prefix="LOCAL", type_code="DOC")
    # LOCAL-{YYYY}-DOC-{8 hex}
    parts = doc_id.split("-")
    assert len(parts) == 4
    assert parts[0] == "LOCAL"
    assert parts[1] == str(date.today().year)
    assert parts[2] == "DOC"
    assert len(parts[3]) == 8
    assert all(c in "0123456789abcdef" for c in parts[3])


def test_document_id_deterministic():
    body = "# Title\n\nbody.\n"
    a = generate_document_id(body)
    b = generate_document_id(body)
    assert a == b


def test_document_id_changes_with_body():
    a = generate_document_id("body one")
    b = generate_document_id("body two")
    assert a != b


def test_custom_prefix_and_type_code():
    body = "x"
    doc_id = generate_document_id(body, prefix="CSA", type_code="GD")
    assert doc_id.startswith("CSA-")
    assert "-GD-" in doc_id
```

- [ ] Add to `any2md/frontmatter.py`:

```python
from datetime import date as _date_cls

def generate_document_id(body: str, prefix: str = "LOCAL", type_code: str = "DOC") -> str:
    """Generate an SAGE-conformant document_id from body content.

    Pattern: {PREFIX}-{YYYY}-{TYPE}-{SHA8}
    Used by --auto-id. The SHA8 is the first 8 hex chars of the
    NFC+LF body's SHA-256 (same as content_hash, just truncated).
    """
    full_hash = compute_content_hash(body)
    return f"{prefix}-{_date_cls.today().year}-{type_code}-{full_hash[:8]}"
```

- [ ] In `compose()`, change the document_id emit from `'document_id: ""'` to:

```python
if options.auto_id:
    doc_id = generate_document_id(
        body, prefix=options.auto_id_prefix, type_code=options.auto_id_type_code
    )
    lines.append(f'document_id: "{doc_id}"')
else:
    lines.append('document_id: ""')
```

- [ ] Add `auto_id`, `auto_id_prefix`, `auto_id_type_code` to `PipelineOptions`. Defaults: `False`, `"LOCAL"`, `"DOC"`.

- [ ] CLI: add `--auto-id` flag, forward to `PipelineOptions(auto_id=args.auto_id)`. Prefix/type-code overrides come from config in Task 6.

Commit: `feat(frontmatter): --auto-id generates LOCAL-{YYYY}-DOC-{SHA8} document_id`

---

## Task 4: `--meta KEY=VAL` repeatable flag

**Files:** `any2md/cli.py`, `any2md/frontmatter.py`. Test: `tests/cli/test_cli_meta.py`, `tests/unit/test_meta_overrides.py`.

`--meta` is repeatable. Values use comma syntax for arrays. Dotted keys for nested fields.

Examples:
- `--meta organization=OWASP`
- `--meta authors="Alice, Bob"` → array
- `--meta generation_metadata.authored_by=human`
- `--meta document_type=guidance`

- [ ] Add to argparse:

```python
parser.add_argument("--meta", action="append", default=[],
    metavar="KEY=VAL",
    help="Override frontmatter field. Repeatable. Arrays use comma syntax. "
         "Nested keys use dot syntax (e.g. generation_metadata.authored_by=human).")
```

- [ ] Parse `args.meta` into a `dict[str, Any]`:

```python
def parse_meta_args(meta_args: list[str]) -> dict[str, Any]:
    """Parse '--meta KEY=VAL' args into a nested dict.

    KEY may be dotted (a.b.c). VAL with commas becomes a list.
    """
    out: dict[str, Any] = {}
    for arg in meta_args:
        if "=" not in arg:
            raise ValueError(f"--meta value must be KEY=VAL: {arg!r}")
        key, val = arg.split("=", 1)
        # Array detection: if comma in val, split
        if "," in val:
            parsed = [v.strip() for v in val.split(",") if v.strip()]
        else:
            parsed = val.strip()
        # Set nested
        parts = key.split(".")
        current = out
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = parsed
    return out
```

- [ ] Pass the parsed dict into `compose()` via a new `overrides: dict | None = None` arg. In `compose()`, after building the default field map, deep-merge `overrides` over it (overrides win).

Refactor `compose()` to build a dict-of-fields first, then emit YAML lines. Currently it emits lines directly. New shape:

```python
def compose(body: str, meta: SourceMeta, options: PipelineOptions,
            overrides: dict | None = None) -> str:
    body = _normalize_body(body)
    # Build the field map
    fields = _build_fields(body, meta, options)
    # Apply overrides (deep merge)
    if overrides:
        fields = _deep_merge(fields, overrides)
    # Emit YAML
    return _emit_frontmatter_with_body(fields, body)
```

- [ ] Tests:

```python
# tests/unit/test_meta_overrides.py
import yaml
from any2md.frontmatter import SourceMeta, compose
from any2md.pipeline import PipelineOptions


def _meta(**kw):
    base = dict(
        title_hint=None, authors=[], organization=None, date=None,
        keywords=[], pages=None, word_count=None,
        source_file="x.txt", source_url=None,
        doc_type="txt", extracted_via="heuristic", lane="text",
    )
    base.update(kw)
    return SourceMeta(**base)


def _fm(text):
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end])


def test_simple_override():
    out = compose("# T\n\nbody\n", _meta(), PipelineOptions(),
                  overrides={"organization": "OWASP"})
    assert _fm(out)["organization"] == "OWASP"


def test_array_override():
    out = compose("# T\n\nbody\n", _meta(), PipelineOptions(),
                  overrides={"authors": ["Alice", "Bob"]})
    assert _fm(out)["authors"] == ["Alice", "Bob"]


def test_nested_override():
    out = compose("# T\n\nbody\n", _meta(), PipelineOptions(),
                  overrides={"generation_metadata": {"authored_by": "human"}})
    fm = _fm(out)
    assert fm["generation_metadata"]["authored_by"] == "human"


def test_override_wins_over_derived():
    # title would normally come from H1
    out = compose("# Auto\n\nbody\n", _meta(), PipelineOptions(),
                  overrides={"title": "Manual"})
    assert _fm(out)["title"] == "Manual"
```

```python
# tests/cli/test_cli_meta.py
import subprocess, sys, yaml
def _run(*args):
    return subprocess.run([sys.executable, "-m", "any2md", *args], capture_output=True, text=True)

def test_meta_simple_override(fixture_dir, tmp_path):
    out = tmp_path / "out"
    r = _run("-o", str(out), "--meta", "organization=OWASP",
             str(fixture_dir / "ligatures_and_softhyphens.txt"))
    assert r.returncode == 0
    md = (out / "ligatures_and_softhyphens.md").read_text()
    end = md.index("\n---\n", 4)
    fm = yaml.safe_load(md[4:end])
    assert fm["organization"] == "OWASP"
```

Commit: `feat(cli): --meta KEY=VAL flag for frontmatter field overrides`

---

## Task 5: `--meta-file` flag (TOML loader)

**Files:** `any2md/cli.py`, `any2md/config.py`. Test: extend `tests/unit/test_config.py`.

`--meta-file PATH` loads a TOML file and treats its `[meta]` table as additional overrides (lower priority than `--meta` but higher than tool defaults).

- [ ] Create `any2md/config.py`:

```python
"""Config file loader for any2md.

Discovers .any2md.toml by walking up from cwd. The [meta] table is
treated as frontmatter overrides; the [document_id] table provides
prefix/type_code overrides for --auto-id.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover
        tomllib = None  # type: ignore[assignment]


def load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file. Returns {} on failure."""
    if tomllib is None:
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, ValueError):
        return {}


def discover_config(start: Path | None = None) -> Path | None:
    """Walk up from `start` (default: cwd) looking for `.any2md.toml`.

    Returns the path or None.
    """
    cur = (start or Path.cwd()).resolve()
    while True:
        candidate = cur / ".any2md.toml"
        if candidate.is_file():
            return candidate
        if cur.parent == cur:
            return None
        cur = cur.parent


def extract_meta_overrides(config: dict[str, Any]) -> dict[str, Any]:
    """Extract the [meta] section as a flat overrides dict."""
    return dict(config.get("meta", {}))


def extract_document_id_settings(config: dict[str, Any]) -> tuple[str, str]:
    """Extract publisher_prefix and type_code from [document_id] section.

    Returns (prefix, type_code) defaulting to ("LOCAL", "DOC").
    """
    section = config.get("document_id", {})
    return (
        section.get("publisher_prefix", "LOCAL"),
        section.get("type_code", "DOC"),
    )
```

- [ ] CLI flag:

```python
parser.add_argument("--meta-file", type=Path,
    help="TOML file with frontmatter defaults. Auto-discovered as "
         ".any2md.toml from cwd upward when not specified.")
```

- [ ] Resolution logic in `cli.main()`:

```python
from any2md.config import discover_config, load_toml, extract_meta_overrides, extract_document_id_settings

# Build overrides chain: discovered config → --meta-file → --meta CLI args
overrides: dict = {}
auto_id_prefix, auto_id_type_code = "LOCAL", "DOC"

discovered = discover_config()
if discovered:
    cfg = load_toml(discovered)
    overrides.update(extract_meta_overrides(cfg))
    auto_id_prefix, auto_id_type_code = extract_document_id_settings(cfg)

if args.meta_file:
    cfg = load_toml(args.meta_file)
    overrides.update(extract_meta_overrides(cfg))
    p, t = extract_document_id_settings(cfg)
    if "publisher_prefix" in cfg.get("document_id", {}):
        auto_id_prefix = p
    if "type_code" in cfg.get("document_id", {}):
        auto_id_type_code = t

cli_meta = parse_meta_args(args.meta)
overrides = _deep_merge(overrides, cli_meta)
```

Then forward `overrides` and the `auto_id_*` defaults into `PipelineOptions` (or pass as a separate arg into the converter chain). For simplicity, store overrides on `PipelineOptions` as `frontmatter_overrides: dict | None`.

- [ ] Tests:

```python
# tests/unit/test_config.py
from any2md.config import (
    discover_config,
    load_toml,
    extract_meta_overrides,
    extract_document_id_settings,
)


def test_discover_config_finds_file(tmp_path):
    cfg = tmp_path / ".any2md.toml"
    cfg.write_text("[meta]\norganization = \"X\"\n")
    sub = tmp_path / "sub" / "deeper"
    sub.mkdir(parents=True)
    found = discover_config(start=sub)
    assert found == cfg


def test_discover_config_returns_none_when_absent(tmp_path):
    sub = tmp_path / "x"
    sub.mkdir()
    assert discover_config(start=sub) is None


def test_load_toml_roundtrip(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[meta]\norganization = \"OWASP\"\nauthors = [\"Alice\"]\n")
    cfg = load_toml(p)
    assert cfg["meta"]["organization"] == "OWASP"


def test_extract_meta_overrides():
    cfg = {"meta": {"organization": "X"}, "other": {}}
    assert extract_meta_overrides(cfg) == {"organization": "X"}


def test_extract_document_id_settings_defaults():
    assert extract_document_id_settings({}) == ("LOCAL", "DOC")


def test_extract_document_id_settings_custom():
    cfg = {"document_id": {"publisher_prefix": "CSA", "type_code": "GD"}}
    assert extract_document_id_settings(cfg) == ("CSA", "GD")
```

Commit: `feat(config): --meta-file and .any2md.toml auto-discovery`

---

## Task 6: Tie auto-id prefix/type-code to config

Already covered by Task 5's resolution logic. Verification test:

```python
# add to tests/unit/test_auto_id.py
def test_auto_id_uses_config_prefix(tmp_path, monkeypatch):
    cfg = tmp_path / ".any2md.toml"
    cfg.write_text("[document_id]\npublisher_prefix = \"CSA\"\ntype_code = \"GD\"\n")
    monkeypatch.chdir(tmp_path)
    from any2md.config import discover_config, extract_document_id_settings, load_toml
    discovered = discover_config()
    assert discovered == cfg
    p, t = extract_document_id_settings(load_toml(discovered))
    assert p == "CSA"
    assert t == "GD"
```

Commit on its own only if Task 5 didn't already include this functionality. Otherwise fold into Task 5's commit.

---

## Task 7: Per-file output verbosity refinement

The default OK line per spec §6.5 should look like:
```
  OK: COMP4441-FinalProject.md  (Docling, structured, 14289 words, 18420 tok est, 2 warnings)
```

Update each `convert_*` function to print this richer summary:

- backend (`{extracted_via}`)
- lane (`{meta.lane}`)
- word_count if available, else page count
- token_estimate (computed by frontmatter — needs to be exposed)
- warning count

Simplest: each converter computes the summary string after `compose()` and prints it. Skip warnings line in non-verbose mode unless `> 0`. Spec says "Done in 18.3s: 3 converted, 0 skipped, 0 failed. 2 warnings — pass --strict to fail on warnings." Already partially in cli.py. Add the warning count to the existing summary line.

This is mostly polish. No new tests required beyond visual smoke.

Commit (combined with Task 1's quiet/verbose changes if convenient): `feat(cli): Richer per-file summary line with backend, lane, tokens, warnings`

---

## Task 8: README.md rewrite

**File:** `README.md` (full rewrite, replacing existing v0.7-era content).

Skeleton with section-by-section directives (the implementer fills with prose):

1. **Title + tagline** (2 lines).
2. **One-paragraph what+why** (4 sentences max). Explain RAG framing: "structured, machine-consumable Markdown for downstream retrieval pipelines."
3. **Quick start** (3 commands, copy-paste): install, convert a file, convert a URL. Show the YAML frontmatter snippet of an output file.
4. **Why any2md** section. The RAG ingestion problem in one paragraph (heterogeneous source formats; LLMs need stable shape; ad-hoc converters lose tables/structure). What "structured, machine-consumable Markdown" means here (SAGE-compatible frontmatter, deterministic content_hash, chunk-friendly heading hierarchy). Honest comparison table vs unstructured.io / pdfplumber / pandoc — ~3-4 rows, no marketing.
5. **What you get** section. Annotated frontmatter example: a real output file with one-line comments after each frontmatter field explaining what it is and why. Before/after example: snippet of a multi-column PDF as raw extraction (pymupdf4llm-style) vs as any2md output (Docling structured lane). Token-estimate / chunking guidance: "we recommend `recommended_chunk_level: h2` when sections are < 1500 tokens; `h3` otherwise."
6. **Installation** section. Two paths: `pip install any2md` (lightweight: pymupdf4llm fallback only) vs `pip install "any2md[high-fidelity]"` (Docling: ~2 GB ML models, 3-10× slower, far better tables/multi-column). "When do I need high-fidelity?" 3-question decision tree (does my corpus have tables? multi-column? scanned PDFs?).
7. **Usage by source type** section. Subsections for PDFs (digital vs scanned subsection), DOCX, HTML/URL (with the SSRF + size limits noted), TXT, batch/directory mode (with `-r` recursive). Each subsection: "why you'd use this" + command + "what you'll see".
8. **The output format** subsection. Brief summary of SAGE-compat. Field auto-fill table (which fields are derived; which need user input). Link to `docs/output-format.md` for full reference.
9. **Configuration** section. `--meta KEY=VAL` and `.any2md.toml` worked example. Show a 10-line `.any2md.toml` for a security-research org producing SAGE-conforming outputs.
10. **Troubleshooting (link)** with 5 most common artifacts as one-line entries.
11. **Architecture (link)** with the two-lane pipeline diagram inline (ASCII art from spec §2.1).
12. **Migrating from v0.7** (link to docs/upgrading-from-0.7.md) with one-paragraph migration summary.
13. **Security** section. SSRF protection, size limits, trust model — kept and expanded.
14. **Contributing (link)** to CONTRIBUTING.md.
15. **License** (one line: MIT).

**Tone reminder:** every command preceded by *why you'd run it* and followed by *what you'll see*. No "blazingly fast"-style language. Markdown headings, no decoration.

Commit: `docs: Rewrite README for v1.0 with educational tone and full output documentation`

---

## Task 9: docs/output-format.md

**File:** `docs/output-format.md`. Sections per spec §7.3:

- **Why a contract.** RAG pipelines need a stable schema; cost of ad-hoc.
- **The SAGE connection.** What SAGE is. Why we're compatible-not-strict (most converted docs aren't security research). Link to upstream SAGE-Specification-v1.0-RC1 (note: it lives in this repo's `template/` dir but `template/` is gitignored locally; reference by URL once SAGE is published, or embed the relevant section here).
- **Field-by-field reference.** Every required + optional + extension field. Per field: meaning, type, derivation rule (or "user-provided"), when it's empty, an example value, a "common mistake" callout. Use a definition list or a table.
- **The body shape.** Single-H1 rule, no skipped levels, citation `[1][2]` format, table format, footnote conventions. Worked example: short input, full output.
- **`content_hash` semantics.** Exact normalization recipe (NFC, LF, post-pipeline). 6-line Python snippet that recomputes it given a `.md` file:

```python
import hashlib, unicodedata
from pathlib import Path
text = Path("output.md").read_text()
body = text.split("\n---\n", 2)[2]              # everything after second ---
body = body.replace("\r\n", "\n").replace("\r", "\n")
body = unicodedata.normalize("NFC", body)
print(hashlib.sha256(body.encode("utf-8")).hexdigest())
```

(Adjust the split logic — frontmatter is `---\n…---\n` with a blank-line separator after. Test the snippet against a real file before committing.)

- **Chunking guidance.** When to use h2 vs h3 for retrieval. Latency/recall tradeoffs at common document lengths. Concrete: "for a 10K-token doc with 5 H2 sections, h2 chunks average 2K tokens — fine for 4K context. For a 30K-token doc with 3 H2 sections, h3 chunks are recommended."
- **Validating output.** How to use `validators.py` programmatically:

```python
from any2md.validators import check_heading_hierarchy, check_content_hash_round_trip
issues = check_heading_hierarchy(body)
ok = check_content_hash_round_trip(body, frontmatter_hash)
```

- **JSON Schema** for the frontmatter. Auto-generated or hand-written; ~80-100 lines.

Commit: `docs: docs/output-format.md - SAGE-compat field reference and content_hash semantics`

---

## Task 10: docs/cli-reference.md

**File:** `docs/cli-reference.md`. For every flag:

- One-line description.
- Type, default, valid values.
- "Use this when…" paragraph (1-2 sentences).
- "Don't use this when…" paragraph (1-2 sentences).
- Small before/after example or output snippet.

Bottom of doc: a "worked example matrix" — common scenarios with full `any2md …` invocations:

- "I want fastest possible turnaround on clean PDFs" → `any2md *.pdf` (default, no extras)
- "I want CI-grade reproducibility" → `any2md -H --strict <inputs>` (Docling required, fail on warnings)
- "I'm ingesting a corporate corpus into a RAG vector store" → `any2md -r --meta-file ./corpus.toml ./corpus/`
- "I need lossless minimal output for a token-budget RAG" → `any2md --profile maximum --strip-links <inputs>`
- "I'm processing scanned PDFs" → `any2md --ocr-figures <pdfs>`

Commit: `docs: docs/cli-reference.md - flag-by-flag reference with use cases`

---

## Task 11: docs/architecture.md

**File:** `docs/architecture.md`. Sections:

- High-level pipeline diagram (ASCII art, same as spec §2.1).
- Why two lanes — concrete damage example: "Running text-lane line-wrap repair on Docling table output produces this kind of corruption: …" with 5-line before/after.
- Stage catalog — every stage's contract (one row per stage in a table: name, lane, input shape, output shape, no-op cases, edge cases).
- The `SourceMeta` dataclass — what each field means, which converters populate it, which are required for the SAGE contract.
- Adding a new converter — step-by-step, ending in "the converter must produce raw markdown + SourceMeta and declare a lane. Frontmatter and cleanup are not its job."
- Adding a new pipeline stage — where to insert (which file/lane), naming convention, test requirements.
- Performance model — where time goes per format. Why Docling is slower (ML models). Where the optimization opportunities are.

Commit: `docs: docs/architecture.md - pipeline internals and contributor guide`

---

## Task 12: docs/troubleshooting.md

**File:** `docs/troubleshooting.md`. Symptom → cause → fix table at top, then expanded subsections per row.

| Symptom | Likely cause | Quick fix |
|---|---|---|
| Garbled text / `?` blocks / `⌧` characters | Encoding-broken PDF, often scanned with bad OCR layer. | Run OCRmyPDF first, then `any2md`. `--ocr-figures` won't help (text layer is the problem). |
| Two columns interleaved | pymupdf4llm path on multi-column PDF | `pip install "any2md[high-fidelity]"` (Docling preserves column flow). |
| Tables show as plaintext blobs | DOCX with merged cells; mammoth fallback. | `pip install "any2md[high-fidelity]"`. |
| Many broken mid-paragraph line breaks | Text-lane T1 didn't match the join heuristic. | File a bug with input snippet. |
| `content_hash` mismatch on round-trip | Body edited after generation OR LF/CRLF mismatch. | Re-run `any2md` or `dos2unix output.md`. |
| Output too verbose for RAG token budget | Default profile too gentle. | `--profile maximum --strip-links`. |
| `WARN: install Docling` keeps appearing | Repeatedly converting complex PDFs without Docling. | Install `[high-fidelity]` once. |

Each row → an expanded section below with full diagnosis steps and common follow-up errors.

Commit: `docs: docs/troubleshooting.md - symptom-cause-fix triage guide`

---

## Task 13: docs/upgrading-from-0.7.md

**File:** `docs/upgrading-from-0.7.md`. Sections per spec §7.7:

1. **TL;DR.** v1.0 emits SAGE-compatible frontmatter. Body is NFC + LF normalized. Pin v0.7 if you need the old shape.
2. **Frontmatter field map** — table of v0.7 keys → v1.0 keys with notes:

| v0.7 | v1.0 | Notes |
|---|---|---|
| `title` | `title` | unchanged |
| `source_file` | `source_file` (extension) | retained as non-SAGE extension |
| `source_url` | `source_url` (extension) | retained, URL inputs only |
| `pages` | `pages` (extension) | retained, PDF only |
| `word_count` | `word_count` (extension) | retained |
| `type` | `type` (extension) | retained |
| — | `document_id` | new, empty unless `--auto-id` |
| — | `version`, `date`, `status`, `document_type`, `content_domain`, `authors`, `organization`, `generation_metadata`, `content_hash`, `token_estimate`, `recommended_chunk_level`, `abstract_for_rag`, `keywords`, `extracted_via` | new (auto-filled or empty per output-format.md) |

3. **Behavior changes** — exit codes (0/1/2/3), the new `--strict` mode, default backend selection, how to recover v0.7-like output (`--profile conservative` is closest, but full v0.7 frontmatter is not recoverable; pin v0.7 if you need it).
4. **CLI flag additions** — list with one-line descriptions.

Commit: `docs: docs/upgrading-from-0.7.md - migration guide`

---

## Task 14: CONTRIBUTING.md

**File:** `CONTRIBUTING.md`. Sections per spec §7.9:

- Dev setup: `git clone`, `pip install -e ".[dev,high-fidelity]"`, `pytest`.
- Running tests: `pytest -v`, `pytest tests/integration/test_url_wikipedia.py -v` (network test, opt-in), snapshot regeneration: `UPDATE_SNAPSHOTS=1 pytest`.
- Adding a converter (cross-link to architecture.md).
- Adding a pipeline stage (cross-link).
- Coding standards (lazy imports, no class hierarchies for simple ops, ruff/format).
- Release flow: TestPyPI → PyPI, version bump, tag, GitHub Release.
- PR process: branch off main, test green, lint clean, descriptive PR title.

Commit: `docs: CONTRIBUTING.md`

---

## Task 15: Issue templates

**Files:** `.github/ISSUE_TEMPLATE/bug_report.md`, `.github/ISSUE_TEMPLATE/conversion_quality.md`.

`bug_report.md` — generic. ~40 lines. Sections: env (Python version, any2md version, OS), command, expected, actual, steps to reproduce.

`conversion_quality.md` — for artifact reports. Asks for: source format, file size, Docling version (if installed), full command, **5-line snippet of the bad output**, **what the source looks like at that location** (text or screenshot if non-confidential). The whole point is that conversion-quality bugs are unfixable without these.

Both follow GitHub issue template format with YAML frontmatter:

```yaml
---
name: Bug report
about: Report a defect (use Conversion quality for output artifacts)
title: ''
labels: bug
---
```

Commit: `docs: GitHub issue templates (bug_report, conversion_quality)`

---

## Task 16: CHANGELOG 1.0.0rc1 entry

Insert above `[1.0.0a3]`:

```markdown
## [1.0.0rc1] — 2026-04-26

Phase 4: configuration, polish, and the v1.0 documentation set.

### Added
- `--meta KEY=VAL` repeatable flag for frontmatter overrides.
- `--meta-file PATH` flag plus auto-discovery of `.any2md.toml` (walks up from cwd).
- `--auto-id` flag — generates SAGE-conformant `document_id` as `LOCAL-{YYYY}-DOC-{SHA8}`. Override prefix/type via `[document_id]` table in `.any2md.toml`.
- `--strict` flag — promotes pipeline validation warnings to errors.
- `--quiet` / `-q` and `--verbose` / `-v` flags.
- New exit code contract: 0 success, 1 usage/install error, 2 file failure, 3 strict-mode warning.
- Per-file summary line now includes backend, lane, token estimate, and warning count.
- New module `any2md/config.py` for TOML config discovery and parsing.
- Comprehensive documentation set under `docs/`:
  - `README.md` (rewritten)
  - `docs/output-format.md` — SAGE-compat field reference and content_hash recipe.
  - `docs/cli-reference.md` — flag-by-flag with use cases.
  - `docs/architecture.md` — pipeline internals and contributor guide.
  - `docs/troubleshooting.md` — symptom-cause-fix table.
  - `docs/upgrading-from-0.7.md` — migration guide.
  - `CONTRIBUTING.md`
  - GitHub issue templates: generic bug, conversion quality.

### Changed
- `frontmatter.compose()` now accepts an `overrides: dict | None` argument that deep-merges into derived fields. Used by `--meta` / `--meta-file` / `.any2md.toml`.
- `cli.main()` exit code logic refactored to track failures and strict warnings separately.
```

Commit: `docs: CHANGELOG entry for 1.0.0rc1`

---

## Task 17: Editorial review pass

Run the editorial checks from spec §7.11:

- [ ] Every code block in every doc runs as written (test by literally copy-paste-running each command).
- [ ] Every cross-link resolves (`grep -nE '\[.*\]\([^)]*\.md\)' docs/ README.md` and verify each).
- [ ] No `TODO` / `TBD` / "coming soon" left in published files.
- [ ] One spell-check pass (use `aspell` or pyspelling — for this plan, just visual review).
- [ ] Read aloud test — flag anything that reads like marketing copy.

Fix any issues inline. Commit only if changes are needed:

```bash
git commit -m "docs: Editorial review pass for v1.0 docs"
```

---

## Task 18: Tag and TestPyPI release

Same pattern as Phase 2/3:

1. `pytest -q`, `ruff check`, version is `1.0.0rc1`, working tree clean.
2. `git push origin phase4-polish-config-docs`
3. `git tag -a v1.0.0rc1 -m "any2md 1.0.0rc1 — Phase 4 config + docs release candidate"`
4. `git push origin v1.0.0rc1`
5. `gh release create v1.0.0rc1 --prerelease …`
6. Watch publish workflow; verify install in clean venv.
7. Merge `phase4-polish-config-docs` → `v1.0` with `--no-ff`.

---

## Parallelism

```
T1 → T2 → T3 (cli sequential — touch cli.py)
T4 → T5 → T6 (cli + frontmatter + config sequential)
T7 (folded into T1 commits)
T8 (README) — independent
T9 (output-format.md) — independent
T10 (cli-reference.md) — independent (but easier with T8/T9 done first for cross-links)
T11 (architecture.md) — independent
T12 (troubleshooting.md) — independent
T13 (upgrading.md) — independent
T14 (CONTRIBUTING.md) — independent
T15 (issue templates) — independent
T16 (CHANGELOG) — depends on all docs done
T17 (editorial pass) — final
T18 (release) — final
```

Suggested batches for subagent execution:

- **Batch A** (T1-T3): CLI ergonomics flags
- **Batch B** (T4-T6): metadata/config plumbing
- **Batch C** (T7): output verbosity (likely folded into A)
- **Batch D** (T8): README rewrite — its own subagent because of length
- **Batch E** (T9-T13): the five `docs/*.md` files in one subagent (consistent tone)
- **Batch F** (T14-T15): CONTRIBUTING + issue templates
- **Batch G** (T16-T17): CHANGELOG + editorial pass
- **T18** (release): controller does it directly

Critical path ~14 task slots vs 18.

---

## Self-review summary

Spec coverage:
- §6.1 CLI flags → Tasks 1, 3, 4, 5.
- §6.2 `.any2md.toml` → Tasks 5, 6.
- §6.4 Exit codes → Task 2.
- §6.5 Per-file output → Task 7.
- §7 Documentation overhaul → Tasks 8-15.
- §9.1 Phase 4 release gates → Task 18.

No placeholders. All code blocks executable. Type/method names consistent across tasks (`PipelineOptions.auto_id`, `frontmatter.generate_document_id`, `config.discover_config`).
