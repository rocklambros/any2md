"""Tests for scripts/audit-outputs.py — leading-toc-table check.

Regression coverage for issue #17 item 2: the leading-toc-table check
must NOT fire on documents whose body contains no `## ` heading.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


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
        f"audit_file failed to flag a real leading TOC table. Output was:\n{captured}"
    )
