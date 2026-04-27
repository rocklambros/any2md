# any2md v1.0.4 — Issue #17 Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `any2md` v1.0.4 with two surgical fixes from issue #17 — `dedupe_toc_table` leader-dot normalization (pipeline) and `leading-toc-table` H2-guard (audit script) — through PR → TestPyPI rc → PyPI stable → local install with `[high-fidelity]` extras → close issue.

**Architecture:** Single feature branch (`fix/issue-17-toc-followups`) with two disjoint code changes implementable in parallel by subagents in isolated worktrees. Sequential post-implementation steps for version bump, CI gating, and release plumbing. The repo's existing `publish.yml` triggers on GitHub release events: `prerelease=true` → TestPyPI, `prerelease=false` → PyPI.

**Tech Stack:** Python 3.10+, hatchling, pytest, ruff, GitHub Actions, PyPI/TestPyPI Trusted Publishing (OIDC), `gh` CLI.

**Spec:** `docs/superpowers/specs/2026-04-26-issue-17-toc-followups-design.md`
**Issue:** https://github.com/rocklambros/any2md/issues/17

---

## File Map

**New files:**
- `tests/unit/scripts/__init__.py` (empty marker)
- `tests/unit/scripts/test_audit_outputs.py` (audit-script tests)

**Modified files:**
- `any2md/pipeline/text.py` — add `_LEADER_DOT_RE`, normalize cells in `dedupe_toc_table`
- `any2md/__init__.py` — bump `__version__` to `"1.0.4"`
- `scripts/audit-outputs.py` — guard leading-TOC check on `\n## ` presence (also: first-time tracked in git)
- `tests/unit/pipeline/test_text_dedupe_toc_table.py` — add leader-dot test
- `CHANGELOG.md` — prepend `## [1.0.4]` entry

**Untouched:** `any2md/pipeline/structured.py`, `any2md/pipeline/__init__.py`, `any2md/heuristics.py`, all other text.py functions.

---

## Task 0: Setup — branch and baseline

**Files:** none modified

- [ ] **Step 1: Verify clean working tree on `main`**

```bash
cd /Users/klambros/github_projects/any2md
git status
git rev-parse --abbrev-ref HEAD
```

Expected: working tree clean (the design-doc commit `554bf41` already landed on `main`); branch is `main`. The untracked `scripts/audit-outputs.py` is expected and is handled in Task B.

- [ ] **Step 2: Create the feature branch**

```bash
git checkout -b fix/issue-17-toc-followups
git rev-parse --abbrev-ref HEAD
```

Expected output: `fix/issue-17-toc-followups`

- [ ] **Step 3: Confirm pytest baseline is green on the branch**

```bash
pip install -e '.[dev]'
pytest tests/ -q
```

Expected: all tests pass (baseline). If anything fails on `main` HEAD, STOP and surface — do not start changes against a broken baseline.

- [ ] **Step 4: Confirm ruff baseline is green**

```bash
ruff check . && ruff format --check .
```

Expected: zero violations. Same baseline rule as above.

---

## Task A: Pipeline fix — leader-dot normalization in `dedupe_toc_table`

**Files:**
- Modify: `any2md/pipeline/text.py` (add module constant + edit `dedupe_toc_table` loop near line 263)
- Test: `tests/unit/pipeline/test_text_dedupe_toc_table.py` (extend)

**Parallelizable with Task B** — can run in a separate worktree concurrently.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/pipeline/test_text_dedupe_toc_table.py`:

```python
def test_strips_toc_table_with_leader_dot_padding():
    """Docling renders TOC entries as 'Title.................Page' — the
    leader-dot run must be stripped before matching against body headings.

    Regression for issue #17 item 1.
    """
    doc = """\
# Document Title

| # | Section | Page |
|---|---------|------|
| 1 | 1.1. Purpose............................................................................. | 1 |
| 2 | 1.2. Scope................................................................................ | 2 |
| 3 | 2.1. Backup Frequency................................................................. | 5 |
| 4 | 2.2. Retention.......................................................................... | 8 |

## 1.1. Purpose

Body of purpose.

## 1.2. Scope

Body of scope.

## 2.1. Backup Frequency

Body of backup frequency.

## 2.2. Retention

End body.
"""
    out = dedupe_toc_table(doc, PipelineOptions(profile="aggressive"))
    # Table content gone (the leader-dot padded entries should not survive)
    assert "Purpose..............." not in out
    assert "|---|---------|------|" not in out
    # Headings still present
    assert "## 1.1. Purpose" in out
    assert "## 2.2. Retention" in out
```

- [ ] **Step 2: Run the test to verify it FAILS**

```bash
pytest tests/unit/pipeline/test_text_dedupe_toc_table.py::test_strips_toc_table_with_leader_dot_padding -v
```

Expected: FAIL — the assertion `assert "Purpose..............." not in out` fails because the current code keeps the table (overlap stays below 70% since `"1.1. purpose............"` ≠ `"1.1. purpose"`).

- [ ] **Step 3: Implement the fix in `any2md/pipeline/text.py`**

Add the module-level constant just above `_TABLE_ROW_RE` (around line 202):

```python
_LEADER_DOT_RE = re.compile(r"\.{3,}.*$")
```

Replace the cell-extraction loop inside `dedupe_toc_table` (lines 263-268). The current block is:

```python
            # Extract title text from non-numeric cells.
            toc_titles: set[str] = set()
            for row in entry_rows:
                cells = _split_table_cells(row)
                for cell in cells:
                    if cell and not cell.replace(".", "").isdigit():
                        toc_titles.add(cell.lower())
```

Change it to:

```python
            # Extract title text from non-numeric cells.
            # Strip leader-dot padding ('Purpose............') before matching —
            # Docling renders TOC entries with dotted page-number padding and
            # the body-heading equivalent does not contain the dots.
            toc_titles: set[str] = set()
            for row in entry_rows:
                cells = _split_table_cells(row)
                for cell in cells:
                    normalized = _LEADER_DOT_RE.sub("", cell).strip()
                    if normalized and not normalized.replace(".", "").isdigit():
                        toc_titles.add(normalized.lower())
```

Do **not** modify the text-block TOC site at line 182 — `_TOC_LINE_RE` (line 154) already consumes the leader-dot run via its `(?:\s*\.{3,}|\s+)\s*\d+\s*$` suffix, so `m.group(1)` is leader-dot-free.

- [ ] **Step 4: Run the new test to verify it PASSES**

```bash
pytest tests/unit/pipeline/test_text_dedupe_toc_table.py::test_strips_toc_table_with_leader_dot_padding -v
```

Expected: PASS.

- [ ] **Step 5: Run the full `dedupe_toc_table` test file to confirm no regressions**

```bash
pytest tests/unit/pipeline/test_text_dedupe_toc_table.py -v
```

Expected: 5 tests PASS (4 existing + 1 new).

- [ ] **Step 6: Run the full pipeline test directory**

```bash
pytest tests/unit/pipeline/ -q
```

Expected: all tests PASS. If a snapshot drifts, inspect the diff — if the new behavior is correct, regenerate that one snapshot only (`pytest --snapshot-update tests/unit/pipeline/<file>`); if it indicates over-stripping, narrow the regex to require a minimum dot-run length of 4 (`r"\.{4,}.*$"`) and re-run.

- [ ] **Step 7: Commit Task A**

```bash
git add any2md/pipeline/text.py tests/unit/pipeline/test_text_dedupe_toc_table.py
git commit -m "$(cat <<'EOF'
fix(pipeline): T7 dedupe_toc_table strips leader-dot padding from TOC cells

Docling renders TOC entries with dotted page-number padding
("1.1. Purpose..........Page"), so the cell-vs-body-heading
equality check kept tables that should have been stripped.
Normalize the cell with `re.sub(r'\.{3,}.*$', '', cell).strip()`
before lower-casing and adding to the comparison set.

Text-block TOC site (line 182) already strips leader dots via
_TOC_LINE_RE's capture group — only the table-variant site
needed the fix.

Refs #17.
EOF
)"
```

---

## Task B: Audit-script fix — H2-guard the leading-TOC check

**Files:**
- Modify: `scripts/audit-outputs.py` (line ~125)
- Create: `tests/unit/scripts/__init__.py`
- Test: `tests/unit/scripts/test_audit_outputs.py`

**Parallelizable with Task A** — can run in a separate worktree concurrently.

**Important:** `scripts/audit-outputs.py` is currently UNTRACKED in git (it exists locally but was never committed). Step 1 below tracks it as-is, then Step 2+ apply the fix.

- [ ] **Step 1: Track `scripts/audit-outputs.py` in git as-is (no edits yet)**

```bash
git add scripts/audit-outputs.py
git status
```

Expected: `scripts/audit-outputs.py` shown as `new file:` in staged changes. Do NOT commit yet — bundle with the test infra in Step 8.

- [ ] **Step 2: Create the test directory marker**

Create `tests/unit/scripts/__init__.py` as an empty file:

```bash
touch tests/unit/scripts/__init__.py
```

Verify:

```bash
ls tests/unit/scripts/
```

Expected: `__init__.py` listed.

- [ ] **Step 3: Write the failing tests**

Create `tests/unit/scripts/test_audit_outputs.py` with this exact content:

```python
"""Tests for scripts/audit-outputs.py — leading-toc-table check.

Regression coverage for issue #17 item 2: the leading-toc-table check
must NOT fire on documents whose body contains no `## ` heading.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_audit_module():
    """Load scripts/audit-outputs.py as a module (hyphen in filename
    blocks regular `import`)."""
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "audit-outputs.py"
    spec = importlib.util.spec_from_file_location("audit_outputs", script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_outputs"] = module
    spec.loader.exec_module(module)
    return module


_FRONTMATTER = """---
title: Test Doc
authors: []
source_file: test.pdf
---

"""


def _write_md(tmp_path: Path, body: str) -> Path:
    """Write a minimally-valid .md file (frontmatter + body) and return its path."""
    p = tmp_path / "doc.md"
    p.write_text(_FRONTMATTER + body, encoding="utf-8")
    return p


def test_no_h2_with_trailing_table_is_not_flagged(tmp_path, capsys):
    """Body with no H2 and a trailing GFM table must NOT trigger
    leading-toc-table (regression for issue #17 item 2)."""
    audit = _load_audit_module()
    body = (
        "Some intro paragraph.\n\n"
        "More body content with no headings at all.\n\n"
        "| col1 | col2 |\n"
        "|------|------|\n"
        "| a    | b    |\n"
        "| c    | d    |\n"
    )
    path = _write_md(tmp_path, body)
    audit.audit_file(path)
    captured = capsys.readouterr().out
    assert "leading-toc-table" not in captured, (
        f"audit_file falsely flagged leading-toc-table on a no-H2 trailing "
        f"table doc. Output was:\n{captured}"
    )


def test_leading_table_before_h2_is_still_flagged(tmp_path, capsys):
    """Body with a table at the top followed by a `## Heading` MUST still
    trigger leading-toc-table (guards against over-correction of the fix)."""
    audit = _load_audit_module()
    body = (
        "| Section | Page |\n"
        "|---------|------|\n"
        "| Intro   | 1    |\n"
        "| Body    | 2    |\n"
        "\n"
        "## Intro\n\n"
        "Real content here.\n"
    )
    path = _write_md(tmp_path, body)
    audit.audit_file(path)
    captured = capsys.readouterr().out
    assert "leading-toc-table" in captured, (
        f"audit_file failed to flag a real leading TOC table. "
        f"Output was:\n{captured}"
    )
```

- [ ] **Step 4: Run the new tests to verify the false-positive test FAILS and the true-positive test PASSES**

```bash
pytest tests/unit/scripts/test_audit_outputs.py -v
```

Expected:
- `test_no_h2_with_trailing_table_is_not_flagged` → FAIL (this is the bug being fixed; the audit currently flags it)
- `test_leading_table_before_h2_is_still_flagged` → PASS (current behavior is correct for this case)

- [ ] **Step 5: Apply the fix to `scripts/audit-outputs.py`**

Find the block at line 124-128:

```python
    # Leading TOC table (table appearing before any H2)
    pre_h2 = body.split("\n## ", 1)[0]
    if LEADING_TABLE_BEFORE_H2_RE.search(pre_h2):
        flag(path, "leading-toc-table", "body has table before first H2")
        flags += 1
```

Replace it with:

```python
    # Leading TOC table (table appearing before any H2). Skip when the body
    # contains no H2 — there is no "leading-TOC region" defined and any
    # table in the doc would otherwise false-flag (issue #17 item 2).
    if "\n## " in body:
        pre_h2 = body.split("\n## ", 1)[0]
        if LEADING_TABLE_BEFORE_H2_RE.search(pre_h2):
            flag(path, "leading-toc-table", "body has table before first H2")
            flags += 1
```

- [ ] **Step 6: Run the new tests to verify both PASS**

```bash
pytest tests/unit/scripts/test_audit_outputs.py -v
```

Expected: both tests PASS.

- [ ] **Step 7: Run the full suite to confirm no regressions**

```bash
pytest tests/ -q
```

Expected: all tests PASS.

- [ ] **Step 8: Commit Task B (single commit: track + fix + tests)**

```bash
git add scripts/audit-outputs.py tests/unit/scripts/__init__.py tests/unit/scripts/test_audit_outputs.py
git commit -m "$(cat <<'EOF'
fix(audit): leading-toc-table check requires `\n## ` in body

The `leading-toc-table` check did `body.split("\n## ", 1)[0]`
unconditionally; when the body had no `## ` heading the split
returned the whole body, so any GFM table — even one at the
end — tripped the flag. Guard the check on `"\n## " in body`.

Also tracks `scripts/audit-outputs.py` in git (was previously
local-only), and adds `tests/unit/scripts/test_audit_outputs.py`
covering both the false-positive regression and a true-positive
guard against over-correction.

Refs #17.
EOF
)"
```

---

## Task C: Version bump + CHANGELOG

**Files:**
- Modify: `any2md/__init__.py`
- Modify: `CHANGELOG.md`

**Sequential** — must run AFTER Tasks A and B are merged into the feature branch (this commit covers both fixes).

- [ ] **Step 1: Bump `__version__`**

Edit `any2md/__init__.py`. Current content:

```python
"""Convert PDF, DOCX, HTML, and TXT files to LLM-optimized Markdown."""

__version__ = "1.0.3"
```

Change `"1.0.3"` to `"1.0.4"`. Resulting file:

```python
"""Convert PDF, DOCX, HTML, and TXT files to LLM-optimized Markdown."""

__version__ = "1.0.4"
```

- [ ] **Step 2: Verify the version bump**

```bash
python -c "import any2md; print(any2md.__version__)"
```

Expected output: `1.0.4`

- [ ] **Step 3: Prepend the v1.0.4 CHANGELOG entry**

Edit `CHANGELOG.md`. Insert this block immediately after the line `The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).` and before the existing `## [1.0.3] — 2026-04-26` heading. New entry:

```markdown

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

```

- [ ] **Step 4: Verify CHANGELOG renders correctly**

```bash
head -80 CHANGELOG.md
```

Expected: v1.0.4 entry at the top, v1.0.3 entry below it, no broken markdown.

- [ ] **Step 5: Commit version bump + CHANGELOG**

```bash
git add any2md/__init__.py CHANGELOG.md
git commit -m "chore: Bump to 1.0.4 — release notes for issue #17 follow-ups"
```

---

## Task D: Local verification — full pytest + ruff + audit sanity

**Files:** none modified

- [ ] **Step 1: Full pytest suite**

```bash
pytest tests/ -q
```

Expected: all tests PASS.

- [ ] **Step 2: Ruff lint + format check (matches CI's `quality` job)**

```bash
ruff check . && ruff format --check .
```

Expected: zero violations.

- [ ] **Step 3: Audit-script smoke run on local `output/` dir (if any markdown present)**

```bash
if find output -maxdepth 2 -name '*.md' -print -quit | grep -q .; then
    python scripts/audit-outputs.py output/ 2>&1 | tail -10
else
    echo "No local output/ markdown to audit — skipping sanity run."
fi
```

Expected: either skipped, or zero false-positive `leading-toc-table` flags on docs with no H2 in body.

- [ ] **Step 4: Verify branch is ready to push**

```bash
git log --oneline main..HEAD
```

Expected: 3 commits — Task A pipeline fix, Task B audit fix, Task C version bump + CHANGELOG.

---

## Task D.5: Subagent review pass (correctness + security)

**Files:** none modified (review only — gating step before pushing the branch)

**Sequential** — runs after Task D, before Task E. The spec's "Phase C" review pass.

- [ ] **Step 1: Dispatch two reviewer subagents in parallel**

In a single message, launch both:

- **Agent 1 (`feature-dev:code-reviewer`)** — Prompt: "Review the diff `git diff main..HEAD` on the `fix/issue-17-toc-followups` branch in `/Users/klambros/github_projects/any2md`. Validate against issue #17 fix sketches: (1) `dedupe_toc_table` should strip leader-dot padding from TOC cells before matching against body H2/H3 titles; the text-block site at `_TOC_LINE_RE` should NOT be modified because its regex already captures only the title. (2) `scripts/audit-outputs.py`'s `leading-toc-table` check must skip when no `## ` is present in the body. Flag scope creep, missing tests, regressions. Report any blockers in under 300 words."
- **Agent 2 (`security-engineer`)** — Prompt: "Security review for the v1.0.4 diff `git diff main..HEAD` on the `fix/issue-17-toc-followups` branch in `/Users/klambros/github_projects/any2md`. Specifically: (1) ReDoS check on the new `_LEADER_DOT_RE = re.compile(r'\\.{3,}.*\$')` pattern in `any2md/pipeline/text.py` — it's applied per-cell to short table strings; confirm worst-case match time is bounded. (2) Audit-script change in `scripts/audit-outputs.py` — the new `\"\\n## \" in body` check is on attacker-controlled markdown content; confirm no DoS surface beyond the existing regex set. Report blockers in under 200 words."

- [ ] **Step 2: Address blockers (if any)**

If either agent flags a blocker:
1. Fix on the feature branch (no rebase, no force-push).
2. Re-run Task D Step 1 (full pytest) and Step 2 (ruff).
3. Commit the fix with a descriptive message.
4. Re-dispatch only the agent that flagged the issue, scoped to the fix commit.

If both agents return clean, proceed to Task E.

---

## Task E: PR — push, open, wait for CI, merge

**Files:** none modified

- [ ] **Step 1: Push the feature branch**

```bash
git push -u origin fix/issue-17-toc-followups
```

Expected: branch published; output shows the new branch URL.

- [ ] **Step 2: Open the PR**

```bash
gh pr create \
  --base main \
  --head fix/issue-17-toc-followups \
  --title "fix(v1.0.4): TOC leader-dot dedupe + audit-script H2 guard (#17)" \
  --body "$(cat <<'EOF'
## Summary
- Pipeline (T7): `dedupe_toc_table` now normalizes leader-dot padding (`Purpose..........`) from TOC cells before matching against body H2/H3 titles. Fixes the SafeBreach-corpus regression where Docling-rendered TOC tables survived the strip pass.
- Audit script: `leading-toc-table` check is now gated on `"\n## "` being present in the body — eliminates false positives on documents whose only GFM table sits at the end with no H2 in the body.
- `scripts/audit-outputs.py` is now tracked in version control (was previously local-only).

Closes #17.

## Test plan
- [x] New `test_strips_toc_table_with_leader_dot_padding` — leader-dot padded TOC cells get stripped under aggressive profile.
- [x] New `tests/unit/scripts/test_audit_outputs.py` — false-positive trailing-table case is NOT flagged; true-positive leading-table-before-H2 case IS still flagged.
- [x] Full `pytest tests/` green locally.
- [x] `ruff check . && ruff format --check .` green locally.

## Repro (from issue #17)
```sh
any2md "<SafeBreach Security Policies 2025>/Backup.pdf" --output-dir /tmp/repro --no-arxiv-lookup --force
python3 scripts/audit-outputs.py /tmp/repro   # before: leading-toc-table flag; after: clean
```
EOF
)"
```

Expected: PR URL printed. Save it as `PR_URL` for later steps.

- [ ] **Step 3: Wait for required CI checks to pass**

```bash
gh pr checks --watch
```

Expected: `quality`, `smoke (3.10)`, `smoke (3.12)`, `smoke (3.13)`, `audit` all show ✓ pass.

If any check fails: STOP, fetch logs with `gh run view --log-failed`, root-cause, push fix commit, re-run this step. Do NOT bypass with `--admin` — required status checks must actually pass.

- [ ] **Step 4: Resolve any PR conversations (none expected)**

```bash
gh pr view --json reviewDecision,comments
```

Expected: `comments` empty or all resolved. If unresolved threads exist, address them before merging.

- [ ] **Step 5: Merge the PR (squash, admin-override for self-merge under enforce_admins)**

```bash
gh pr merge --squash --admin --delete-branch
```

Expected: PR shows as merged; remote feature branch deleted.

- [ ] **Step 6: Sync local `main` with the squashed merge**

```bash
git checkout main
git pull --ff-only origin main
git log --oneline -3
```

Expected: top commit is the squash-merge of v1.0.4 changes; `__version__` is `1.0.4` on main:

```bash
python -c "import any2md; print(any2md.__version__)"
```

---

## Task F: TestPyPI release (prerelease tag)

**Files:** none modified

- [ ] **Step 1: Create the prerelease tag**

```bash
git tag v1.0.4-rc1
git push origin v1.0.4-rc1
```

Expected: tag published. The publish workflow validator allows `tag.startswith(version + "-")`, so `v1.0.4-rc1` is accepted while `__version__` stays at `1.0.4`.

- [ ] **Step 2: Create the GitHub release as prerelease**

```bash
gh release create v1.0.4-rc1 \
  --prerelease \
  --title "v1.0.4-rc1 (TestPyPI)" \
  --notes "$(cat <<'EOF'
TestPyPI prerelease for v1.0.4 — see CHANGELOG.md for full notes.

Closes follow-ups from #17:
- T7 dedupe_toc_table strips leader-dot padding from TOC cells.
- audit-outputs.py leading-toc-table check requires `\n## ` in body.

Install from TestPyPI:
```sh
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            'any2md[high-fidelity]==1.0.4'
```
EOF
)"
```

Expected: release URL printed.

- [ ] **Step 3: Watch the publish workflow**

```bash
gh run watch --exit-status $(gh run list --workflow publish.yml --limit 1 --json databaseId -q '.[0].databaseId')
```

Expected: `validate`, `smoke`, and `publish-testpypi` jobs all succeed. `publish-pypi` is skipped (the `if: github.event.release.prerelease == false` gate).

- [ ] **Step 4: Verify TestPyPI listing**

```bash
sleep 30   # TestPyPI index propagation
curl -sS https://test.pypi.org/pypi/any2md/json | python -c "import json,sys; d=json.load(sys.stdin); print('latest:', d['info']['version']); print('releases:', sorted(d['releases'].keys())[-5:])"
```

Expected: `1.0.4` listed under releases (TestPyPI normalizes `1.0.4-rc1` to PEP 440 `1.0.4rc1`).

---

## Task G: Smoke install from TestPyPI

**Files:** none modified

- [ ] **Step 1: Create throwaway venv and install with `[high-fidelity]` extras**

```bash
rm -rf /tmp/any2md-tp && python3 -m venv /tmp/any2md-tp
source /tmp/any2md-tp/bin/activate
pip install --quiet --upgrade pip
pip install \
    --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    'any2md[high-fidelity]==1.0.4rc1'
```

Expected: install succeeds. The `--extra-index-url` is critical because TestPyPI does NOT mirror docling and other dependencies — they resolve from real PyPI.

- [ ] **Step 2: Verify version + CLI + extras importable**

```bash
any2md --version || any2md --help | head -3
python -c "import any2md; print('any2md', any2md.__version__)"
python -c "import docling; print('docling OK')"
```

Expected: `any2md 1.0.4`, `docling OK`. (CLI prints `--help` if no `--version` flag is registered — either is fine as a smoke signal.)

- [ ] **Step 3: Quick functional smoke — convert a tiny test fixture if present**

```bash
TEST_PDF=$(find /Users/klambros/github_projects/any2md/test_docs -name '*.pdf' | head -1)
if [ -n "$TEST_PDF" ]; then
    any2md "$TEST_PDF" --output-dir /tmp/any2md-tp-out --force
    ls /tmp/any2md-tp-out/
    head -20 /tmp/any2md-tp-out/*.md
fi
```

Expected: produces a `.md` with valid YAML frontmatter and body. (Skip silently if no test PDF.)

- [ ] **Step 4: Tear down the throwaway venv**

```bash
deactivate
rm -rf /tmp/any2md-tp /tmp/any2md-tp-out
```

---

## Task H: PyPI release (stable tag)

**Files:** none modified

**GATE:** Only proceed if Tasks F + G fully succeeded (TestPyPI install worked end-to-end with `[high-fidelity]` extras).

- [ ] **Step 1: Create the stable tag**

```bash
git tag v1.0.4
git push origin v1.0.4
```

Expected: tag published.

- [ ] **Step 2: Create the GitHub release (NOT prerelease)**

```bash
gh release create v1.0.4 \
  --title "v1.0.4" \
  --notes "$(cat <<'EOF'
Patch release. Two follow-ups deferred from v1.0.3 (#17):

- **Pipeline (T7)**: `dedupe_toc_table` now normalizes leader-dot padding (`Purpose..........`) from TOC cells before matching against body H2/H3 titles. Docling-rendered TOC tables now get properly stripped under aggressive/maximum profiles.
- **Audit script**: `scripts/audit-outputs.py` `leading-toc-table` check no longer false-flags documents whose only GFM table sits at the end with no H2 in the body.

See [CHANGELOG.md](https://github.com/rocklambros/any2md/blob/main/CHANGELOG.md#104--2026-04-26) for full notes.

Install:
```sh
pip install --upgrade 'any2md[high-fidelity]==1.0.4'
```
EOF
)"
```

Expected: release URL printed.

- [ ] **Step 3: Watch the publish workflow**

```bash
gh run watch --exit-status $(gh run list --workflow publish.yml --limit 1 --json databaseId -q '.[0].databaseId')
```

Expected: `validate`, `smoke`, and `publish-pypi` jobs all succeed; `publish-testpypi` is skipped (the `if: github.event.release.prerelease == true` gate).

- [ ] **Step 4: Verify PyPI listing**

```bash
sleep 30
curl -sS https://pypi.org/pypi/any2md/json | python -c "import json,sys; d=json.load(sys.stdin); print('latest:', d['info']['version']); print('files:', [f['filename'] for f in d['urls']])"
```

Expected: `latest: 1.0.4`, sdist + wheel filenames listed.

---

## Task I: System install with `[high-fidelity]` extras

**Files:** none modified

- [ ] **Step 1: Upgrade in the user's system Python**

```bash
pip install --upgrade 'any2md[high-fidelity]==1.0.4'
```

Expected: `any2md` upgraded from 1.0.3 → 1.0.4; docling installed/up-to-date.

- [ ] **Step 2: Verify version + extras**

```bash
any2md --version || any2md --help | head -3
python -c "import any2md; print('any2md', any2md.__version__)"
python -c "import docling; print('docling', getattr(docling, '__version__', 'OK'))"
```

Expected: `any2md 1.0.4`, docling importable.

- [ ] **Step 3: Functional sanity check — convert one local PDF**

```bash
TEST_PDF=$(find /Users/klambros/github_projects/any2md/test_docs -name '*.pdf' | head -1)
if [ -n "$TEST_PDF" ]; then
    rm -rf /tmp/any2md-system-out
    any2md "$TEST_PDF" --output-dir /tmp/any2md-system-out --force
    ls -la /tmp/any2md-system-out/
    head -25 /tmp/any2md-system-out/*.md
fi
```

Expected: valid `.md` produced, frontmatter intact, body content present. If no test PDF available, skip and rely on `--help` signal from Step 2.

- [ ] **Step 4: Cleanup**

```bash
rm -rf /tmp/any2md-system-out
```

---

## Task J: Close issue #17 + final cleanup

**Files:** none modified

- [ ] **Step 1: Capture URLs for the close-out comment**

```bash
PR_URL=$(gh pr list --state merged --search "fix(v1.0.4)" --json url -q '.[0].url')
RELEASE_URL=$(gh release view v1.0.4 --json url -q '.url')
echo "PR: $PR_URL"
echo "Release: $RELEASE_URL"
```

Expected: both URLs printed (non-empty).

- [ ] **Step 2: Close issue #17 with reference comment**

```bash
gh issue close 17 --comment "$(cat <<EOF
Shipped in **v1.0.4**.

- PR: $PR_URL
- Release: $RELEASE_URL
- PyPI: https://pypi.org/project/any2md/1.0.4/

Both follow-ups addressed:
1. T7 \`dedupe_toc_table\` strips leader-dot padding from TOC cells before matching against body headings.
2. \`scripts/audit-outputs.py\` \`leading-toc-table\` check is gated on \`"\n## "\` presence in body — false-positive trailing-table flags eliminated.
EOF
)"
```

Expected: issue #17 closed; comment posted.

- [ ] **Step 3: Verify issue state**

```bash
gh issue view 17 --json state,closedAt -q '"state: " + .state + " closedAt: " + .closedAt'
```

Expected: `state: CLOSED closedAt: <recent timestamp>`.

- [ ] **Step 4: Worktree + working-tree cleanup**

```bash
git worktree prune
git worktree list
git status
```

Expected: only the main worktree listed; working tree clean on `main`.

- [ ] **Step 5: Final smoke**

```bash
git log --oneline -5
```

Expected: top commit is the squash-merge for v1.0.4; tag `v1.0.4` exists (`git tag --list 'v1.0.4*'`).

---

## Summary of Commits

| Task | Branch | Commit message |
|---|---|---|
| A | `fix/issue-17-toc-followups` | `fix(pipeline): T7 dedupe_toc_table strips leader-dot padding from TOC cells` |
| B | `fix/issue-17-toc-followups` | `fix(audit): leading-toc-table check requires \n## in body` |
| C | `fix/issue-17-toc-followups` | `chore: Bump to 1.0.4 — release notes for issue #17 follow-ups` |
| Merge | `main` | (squash) `fix(v1.0.4): TOC leader-dot dedupe + audit-script H2 guard (#17)` |

## Tags Created

- `v1.0.4-rc1` (prerelease, → TestPyPI)
- `v1.0.4` (stable, → PyPI)

## Branch Protection Compliance

- Required status checks (`quality`, `smoke (3.10/3.12/3.13)`, `audit`): all must be green before merge — confirmed in Task E Step 3.
- `enforce_admins=true`: admin-merge does NOT bypass status checks; `--admin` flag is used only to satisfy `require_last_push_approval` for self-merge under 0-required-reviewers — confirmed in Task E Step 5.
- `required_conversation_resolution=true`: Task E Step 4.
- `allow_force_pushes=false`: never force-pushed to `main`.

## Risk Mitigations (active in this plan)

| Risk | Mitigation step |
|---|---|
| Snapshot drift in pipeline tests | Task A Step 6 inspects diffs before regenerating |
| TestPyPI dep resolution misses docling | Task G Step 1 uses `--extra-index-url` to fall back to PyPI for non-package deps |
| Tag/version mismatch | `publish.yml`'s `validate` job enforces; verified by tag format `v1.0.4-rc1` matching `1.0.4` via `tag.startswith(version + "-")` |
| Race between agent worktrees | Tasks A and B touch disjoint files — merge into feature branch is conflict-free by construction |
