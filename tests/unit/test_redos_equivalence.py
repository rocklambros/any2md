"""Behavior-equivalence fuzz for the v1.2.1 ReDoS rewrites.

Each rewritten parser is checked against the regex it replaced, kept here
as an oracle. Inputs are short, so the old patterns are still fast. Exact
agreement is required on well-formed input. Where the rewrite knowingly
differs on degenerate input, the test pins down the direction: the new
code only ever rejects junk the old code accepted.
"""

from __future__ import annotations

import random
import re

from any2md import heuristics
from any2md.frontmatter import derive_title
from any2md.pipeline.text import (
    _body_heading_titles,
    _is_contact_email_line,
    _toc_title,
)

N = 20_000

OLD_TOC = re.compile(r"^\s*(?:[\d.]+\s+)?(.+?)(?:\s*\.{3,}|\s+)\s*\d+\s*$")
OLD_BODY_HEADING = re.compile(r"^#{2,3}\s+(.+?)\s*$", re.MULTILINE)
OLD_FIRST_H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
OLD_CONTACT = re.compile(r"^Contact:.*@.*\..*$", re.IGNORECASE)
OLD_BYLINE = re.compile(
    r"^[A-Z][A-Z .'\-]{2,}(?:\s+\d+(?:\s*,\s*\d+)*)?"
    r"(?:\s*,\s*[A-Z][A-Z .'\-]{2,}(?:\s+\d+(?:\s*,\s*\d+)*)?)+\s*$"
)
OLD_TOC_HINT = re.compile(r"\.{3,}\s*\d+|^\s*page\s+\d+", re.IGNORECASE)
OLD_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def _rand(rng: random.Random, alphabet: str, max_len: int) -> str:
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, max_len)))


def test_toc_title_matches_old_regex_except_empty_titles():
    rng = random.Random(1)
    for _ in range(N):
        line = _rand(rng, " .1Ab\t", 14)
        m = OLD_TOC.match(line)
        old = m.group(1).strip() if m else None
        new = _toc_title(line)
        if old != new:
            # Only degenerate "titles": empty, dots, or bare numbering. The
            # old regex's answer there depended on whitespace counts.
            assert old is not None and old.strip(".") == "", (line, old, new)
            assert new is None or new.strip(".0123456789") == "", (line, old, new)


def _heading_doc(rng: random.Random) -> str:
    lines = []
    for _ in range(rng.randint(1, 5)):
        kind = rng.choice(["h1", "h2", "h3", "h4", "text", "blank"])
        word = rng.choice("ab") + _rand(rng, "ab #\t*_", 8)
        lines.append(
            {
                "h1": "# " + word,
                "h2": "## " + word,
                "h3": "### " + word,
                "h4": "#### " + word,
                "text": word.lstrip("#"),
                "blank": "",
            }[kind]
        )
    return "\n".join(lines)


def test_body_heading_titles_match_old_regex_on_single_line_headings():
    rng = random.Random(2)
    for _ in range(N):
        doc = _heading_doc(rng)
        old = {m.group(1).strip().lower() for m in OLD_BODY_HEADING.finditer(doc)}
        assert _body_heading_titles(doc) == old, doc


def test_derive_title_matches_old_regex_on_single_line_headings():
    rng = random.Random(3)
    for _ in range(N):
        doc = _heading_doc(rng)
        m = OLD_FIRST_H1.search(doc)
        old = (re.sub(r"[*_]+", "", m.group(1)).strip() if m else "") or "fallback"
        assert derive_title(doc, None, "fallback") == old, doc


def test_derive_title_ignores_bare_hash_line():
    # The old \s+ crossed the newline and took "foo" as the H1 title.
    assert derive_title("#\nfoo\n", None, "fallback") == "fallback"


def test_contact_line_matches_old_regex():
    rng = random.Random(4)
    for _ in range(N):
        line = rng.choice(["Contact:", "contact:", "CONTACT:", "Contac:", ""])
        line += _rand(rng, "a@.x ", 12)
        assert _is_contact_email_line(line) == bool(OLD_CONTACT.match(line)), line


def test_byline_never_accepts_what_old_rejected():
    rng = random.Random(5)
    for _ in range(N):
        line = _rand(rng, "AB ,1.'", 22)
        if heuristics._ACADEMIC_BYLINE_RE.match(line):
            assert OLD_BYLINE.match(line), line


def test_byline_still_accepts_real_bylines():
    for line in [
        "PHILIP MOREIRA TOMEI 1, 2, RUPAL JAIN 2, 3",
        "JANE DOE, JOHN SMITH",
        "AL GORE, O'NEIL SMITH-JONES 3",
    ]:
        assert heuristics._ACADEMIC_BYLINE_RE.match(line), line


def test_toc_hint_matches_old_regex():
    rng = random.Random(6)
    for _ in range(N):
        line = _rand(rng, ". 1pageP\t", 12)
        new = bool(heuristics._TOC_LINE_HINTS_RE.search(line))
        assert new == bool(OLD_TOC_HINT.search(line)), line


def test_md_link_strip_matches_old_regex_on_unnested_links():
    rng = random.Random(7)
    for _ in range(N):
        text = _rand(rng, "ab ]()", 6)
        for _ in range(rng.randint(0, 3)):
            label = "a" + _rand(rng, "ab ", 5)
            url = "u" + _rand(rng, "ab/:.", 6)
            text += f"[{label}]({url})" + _rand(rng, "ab ]()", 6)
        assert heuristics._MD_LINK_RE.sub(r"\1", text) == OLD_MD_LINK.sub(
            r"\1", text
        ), text
