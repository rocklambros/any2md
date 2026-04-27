#!/usr/bin/env python3
"""Audit any2md output for quality regressions.

Scans every .md file in the given directory tree and flags files where
the frontmatter or body contains known-bad signals:

  * Title is empty, or matches a cover-page boilerplate string.
  * Authors is empty for an arxiv-pattern source filename.
  * Abstract contains license-notice keywords or markdown link syntax.
  * Body contains HTML entities (&amp;, &lt;, &gt;).
  * Body has trafilatura-fragment artifacts (orphan |, > on their own line).
  * Body has a leading TOC table (markdown table starting before the first H2).
  * Body has the "Author's Contact Information:" line.
  * content_hash doesn't recompute (indicates the file was edited or a bug).

Usage:
  python scripts/audit-outputs.py /path/to/output
  python scripts/audit-outputs.py /path/to/output --strict   # exit 3 if any flagged

Output: TSV — one row per flagged file with columns: filename, signal, detail.
Counts summary at end on stderr.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import unicodedata
from pathlib import Path

import yaml

COVER_PAGE_TITLES = frozenset({
    "international standard", "technical report", "technical specification",
    "publicly available specification", "white paper", "whitepaper",
})
LICENSE_KEYWORDS = (
    "licensed to", "single user licence", "single user license",
    "iso store order", "all rights reserved", "qr code",
    "scan the", "customer feedback form",
)
ARXIV_FILENAME_RE = re.compile(r"(?<![0-9.])\d{4}\.\d{4,5}(?:v\d+)?(?:\.pdf)?$")
HTML_ENTITY_RE = re.compile(r"&(?:amp|lt|gt|quot|#x?\d+);")
ORPHAN_PUNCT_RE = re.compile(r"^\s*[|>]\s*$", re.MULTILINE)
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")
AUTHOR_CONTACT_RE = re.compile(r"^Author(?:'s|s'?)\s*Contact Information:", re.IGNORECASE | re.MULTILINE)
LEADING_TABLE_BEFORE_H2_RE = re.compile(r"\A(?:[^\n]*\n)*?\|[^\n]*\|\s*\n\|[^|\n]*-+", re.MULTILINE)


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return {}, text
    body = text[end + 5:]
    if body.startswith("\n"):
        body = body[1:]
    try:
        fm = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        return {}, body
    return fm, body


def compute_hash(body: str) -> str:
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def flag(name: Path, sig: str, detail: str) -> None:
    print(f"{name}\t{sig}\t{detail}")


def audit_file(path: Path) -> int:
    """Return number of flags for this file."""
    text = path.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    flags = 0

    title = (fm.get("title") or "").strip()
    if not title:
        flag(path, "empty-title", "title field is empty")
        flags += 1
    elif title.lower() in COVER_PAGE_TITLES:
        flag(path, "cover-page-title", title)
        flags += 1

    authors = fm.get("authors") or []
    src = fm.get("source_file") or fm.get("source_url") or ""
    if not authors and ARXIV_FILENAME_RE.search(src):
        flag(path, "arxiv-no-authors",
             f"filename matches arxiv pattern but authors=[] (arxiv lookup failed?): {src}")
        flags += 1

    abstract = fm.get("abstract_for_rag") or ""
    if abstract:
        for kw in LICENSE_KEYWORDS:
            if kw in abstract.lower():
                flag(path, "abstract-license-noise", f"contains '{kw}'")
                flags += 1
                break
        if MARKDOWN_LINK_RE.search(abstract):
            flag(path, "abstract-markdown-link", "abstract contains [text](url) syntax")
            flags += 1

    if HTML_ENTITY_RE.search(body):
        m = HTML_ENTITY_RE.search(body)
        flag(path, "html-entity-in-body", f"first match: {m.group(0)!r}")
        flags += 1

    if ORPHAN_PUNCT_RE.search(body):
        flag(path, "orphan-punctuation", "body has lone | or > line")
        flags += 1

    if AUTHOR_CONTACT_RE.search(body):
        flag(path, "repeated-byline", "body has 'Author's Contact Information:' line")
        flags += 1

    # Leading TOC table (table appearing before any H2). Skip when the body
    # contains no H2 — there is no "leading-TOC region" defined and any
    # table in the doc would otherwise false-flag (issue #17 item 2).
    if "\n## " in body:
        pre_h2 = body.split("\n## ", 1)[0]
        if LEADING_TABLE_BEFORE_H2_RE.search(pre_h2):
            flag(path, "leading-toc-table", "body has table before first H2")
            flags += 1

    expected_hash = fm.get("content_hash")
    if expected_hash:
        actual = compute_hash(body)
        if actual != expected_hash:
            flag(path, "content-hash-mismatch",
                 f"expected {expected_hash[:12]}... got {actual[:12]}...")
            flags += 1

    return flags


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dir", type=Path, help="output directory to audit")
    p.add_argument("--strict", action="store_true", help="exit 3 if any flags fired")
    args = p.parse_args()

    if not args.dir.is_dir():
        print(f"Not a directory: {args.dir}", file=sys.stderr)
        return 1

    md_files = sorted(args.dir.rglob("*.md"))
    if not md_files:
        print(f"No .md files under {args.dir}", file=sys.stderr)
        return 0

    total_files = len(md_files)
    flagged_files = 0
    total_flags = 0
    print("file\tsignal\tdetail")
    for f in md_files:
        n = audit_file(f)
        if n:
            flagged_files += 1
            total_flags += n

    print(
        f"\n{total_files} files audited; {flagged_files} flagged; {total_flags} flags total.",
        file=sys.stderr,
    )
    if args.strict and total_flags > 0:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
