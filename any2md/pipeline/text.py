"""Text-lane pipeline stages.

Phase 3: T1-T6 implemented. These stages run on text-lane output (mammoth
fallback, pymupdf4llm fallback, trafilatura, TXT structurizer) BEFORE the
shared cleanup pipeline. They repair regression artifacts that those
backends leave behind.
"""

from __future__ import annotations

import re
from typing import Callable, TYPE_CHECKING

from any2md.pipeline.blocks import fenced_lines

if TYPE_CHECKING:
    from any2md.pipeline import PipelineOptions

Stage = Callable[[str, "PipelineOptions"], str]


_TERMINAL_PUNCT = ".!?:"
# Setext underlines and thematic breaks (---, ===, ***, ___). Joining one
# onto the line above destroys the heading or rule.
_RULE_RE = re.compile(r"^\s*(?:-{3,}|={3,}|\*{3,}|_{3,})\s*$")
_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*+]|\d+\.|[a-z]\.)\s+", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,6}\s")
_TABLE_RE = re.compile(r"^\s*\|")


def _is_structural(line: str) -> bool:
    """Return True for a line T1 never joins into or out of.

    Fence lines are not tested here. T1 reads them from the block
    scanner, so a backtick line the scanner calls prose (indented four
    spaces, or holding a backtick in its info string) joins like prose,
    and a ``~~~`` fence stays apart.
    """
    return bool(
        _LIST_PREFIX_RE.match(line)
        or _HEADING_RE.match(line)
        or _TABLE_RE.match(line)
        or _RULE_RE.match(line)
    )


def repair_line_wraps(text: str, _options: "PipelineOptions") -> str:
    """T1: Join lines that look like soft wraps inside paragraphs."""
    lines = text.split("\n")
    fenced = fenced_lines(lines)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # End-of-text, empty line, or fenced code: emit and continue
        if i == len(lines) - 1 or line == "" or fenced[i]:
            out.append(line)
            i += 1
            continue

        next_line = lines[i + 1]
        # Stop conditions: structural next line, blank next line, terminal
        # punctuation at end of current line, uppercase start of next line.
        if (
            fenced[i + 1]
            or next_line == ""
            or _is_structural(line)
            or _is_structural(next_line)
            or (line and line[-1] in _TERMINAL_PUNCT)
            or (next_line and next_line[0].isupper())
        ):
            out.append(line)
            i += 1
            continue

        # Join: replace the trailing newline with a single space, drop leading
        # spaces from next.
        merged = line.rstrip() + " " + next_line.lstrip()
        out.append(merged)
        i += 2
    return "\n".join(out)


# A letter run in any script (no digits or underscore), so non-ASCII words
# such as "Straßenbahn" are handled like ASCII ones.
_WORD = r"[^\W\d_]+"
# "word-" at a line end, optional trailing spaces (common in PDF output),
# then the next line's first word. The word boundary keeps "Co-" from
# matching as "o-".
_HYPHEN_WRAP_RE = re.compile(rf"\b({_WORD})-[ \t]*\n[ \t]*({_WORD})")
_COMPOUND_RE = re.compile(rf"\b{_WORD}-{_WORD}\b")
# A hyphen before one of these words is suspended ("first- and second-order"),
# not a broken word.
_SUSPENDED_NEXT = frozenset({"and", "or", "nor", "to"})


def _dehyphenate_prose(segment: str, words: set[str], compounds: set[str]) -> str:
    def _replace(match: re.Match[str]) -> str:
        prefix, suffix = match.group(1), match.group(2)
        # An uppercase next word starts a new name or sentence, and a
        # conjunction marks a suspended hyphen. Neither is a broken word.
        if not suffix[0].islower() or suffix.lower() in _SUSPENDED_NEXT:
            return match.group(0)
        if (prefix + suffix).lower() in words:
            return prefix + suffix
        if f"{prefix}-{suffix}".lower() in compounds:
            return f"{prefix}-{suffix}"
        # No evidence either way. Leave the break for T1, which joins it
        # with a space as before, rather than invent a merged word or a
        # compound the document never uses.
        return match.group(0)

    return _HYPHEN_WRAP_RE.sub(_replace, segment)


def dehyphenate(text: str, _options: "PipelineOptions") -> str:
    """T2: Repair words broken by a hyphen at a line end.

    Runs before T1 so the raw ``word-\nword`` breaks are still visible.
    Decides from evidence in the same document only:

    - joined form appears elsewhere ("cooperation"): merge the word
    - hyphenated form appears elsewhere ("co-pilot"): keep the hyphen
    - suspended hyphen ("first-" before "and"/"or"/"nor"/"to"), an
      uppercase next word, or no evidence: leave the break as is

    Fenced code blocks are never changed.
    """
    if "-" not in text:
        return text
    lowered = text.lower()
    words = set(re.findall(_WORD, lowered))
    compounds = set(_COMPOUND_RE.findall(lowered))

    out: list[str] = []
    prose: list[str] = []
    lines = text.split("\n")
    for line, fenced in zip(lines, fenced_lines(lines)):
        if fenced:
            if prose:
                out.append(_dehyphenate_prose("\n".join(prose), words, compounds))
                prose = []
            out.append(line)
        else:
            prose.append(line)
    if prose:
        out.append(_dehyphenate_prose("\n".join(prose), words, compounds))
    return "\n".join(out)


_AUTHOR_CONTACT_RE = re.compile(
    r"^Author(?:'s|s'?)\s*Contact Information:.*$",
    re.IGNORECASE,
)


def _is_contact_email_line(line: str) -> bool:
    """``Contact: ...@...`` with a ``.`` somewhere after the ``@``.

    String checks, not a regex: ``^Contact:.*@.*\\..*$`` backtracks in
    quadratic time on a long line of ``@`` characters (CWE-1333).
    """
    if not line[:8].lower() == "contact:":
        return False
    rest = line[8:]
    at = rest.find("@")
    return at >= 0 and "." in rest[at + 1 :]


def strip_repeated_byline(text: str, options: "PipelineOptions") -> str:
    """T9: Remove 'Author's Contact Information:' duplicate-byline lines."""
    if options.profile not in ("aggressive", "maximum"):
        return text
    lines = text.split("\n")
    fenced = fenced_lines(lines)
    out: list[str] = []
    for i, line in enumerate(lines):
        if fenced[i]:
            out.append(line)
            continue
        if _AUTHOR_CONTACT_RE.match(line):
            continue
        if i < 50 and _is_contact_email_line(line):
            continue
        out.append(line)
    return "\n".join(out)


_PARA_SPLIT_RE = re.compile(r"\n\s*\n")


def _dedupe_prose(text: str) -> str:
    parts = _PARA_SPLIT_RE.split(text)
    out: list[str] = []
    last = None
    for part in parts:
        normalized = part.strip()
        if normalized and normalized == last:
            continue
        out.append(part)
        last = normalized
    return "\n\n".join(out)


def dedupe_paragraphs(text: str, _options: "PipelineOptions") -> str:
    """T3: Drop a paragraph identical to the immediately previous one.

    Fenced code passes through unchanged. Repeated lines and blank runs
    are often deliberate there, and the paragraph split would collapse
    them.
    """
    lines = text.split("\n")
    fenced = fenced_lines(lines)
    if not any(fenced):
        return _dedupe_prose(text)
    # Dedupe each run of prose lines on its own and copy fenced runs
    # verbatim, so no paragraph spans a fence boundary. Blank lines at
    # the edges of a prose run stay outside the dedupe, since dropping a
    # paragraph also drops the separator it was split from.
    out: list[str] = []
    start = 0
    for k in range(1, len(lines) + 1):
        if k < len(lines) and fenced[k] == fenced[start]:
            continue
        run = lines[start:k]
        if fenced[start]:
            out.extend(run)
        else:
            lo, hi = 0, len(run)
            while lo < hi and not run[lo].strip():
                lo += 1
            while hi > lo and not run[hi - 1].strip():
                hi -= 1
            out.extend(run[:lo])
            if lo < hi:
                out.append(_dedupe_prose("\n".join(run[lo:hi])))
            out.extend(run[hi:])
        start = k
    return "\n".join(out)


# Real TOC entries are short. Longer lines are never TOC candidates, which
# also bounds the work spent on any one line.
_TOC_MAX_LINE = 300
_TOC_NUMBERING_RE = re.compile(r"[\d.]+\s+")


def _rstrip_decimal(s: str) -> str:
    """``s`` without its trailing run of Unicode decimal digits.

    ``isdecimal`` matches what ``\\d`` matched in the old regex, so page
    numbers such as Arabic-Indic or Devanagari digits still count.
    """
    end = len(s)
    while end and s[end - 1].isdecimal():
        end -= 1
    return s[:end]


def _toc_title(line: str) -> str | None:
    """Return the title of a ``Title ..... 12`` / ``1.2 Title 12`` TOC line.

    Parsed procedurally rather than with a regex. The previous pattern,
    ``(.+?)(?:\\s*\\.{3,}|\\s+)\\s*\\d+``, backtracked in cubic time on
    a long whitespace run that did not end in a digit (CWE-1333).
    """
    s = line.strip()
    if not s or len(s) > _TOC_MAX_LINE:
        return None
    unnumbered = _rstrip_decimal(s)
    if unnumbered == s:
        return None  # no trailing page number
    head = unnumbered.rstrip()
    if head.endswith("..."):
        title = head.rstrip(".").rstrip()  # "Title ..... 12"
    elif len(head) < len(unnumbered):
        title = head  # "Title 12": whitespace before the number
    else:
        return None  # digits glued to the title ("Chapter12")
    numbering = _TOC_NUMBERING_RE.match(title)
    if numbering and title[numbering.end() :].strip():
        title = title[numbering.end() :]
    return title.strip() or None


def _body_heading_titles(text: str) -> set[str]:
    """Lowercased titles of every H2/H3 line, parsed line by line.

    Replaces ``^#{2,3}\\s+(.+?)\\s*$``, which backtracked in quadratic time
    on a heading holding a long whitespace run (CWE-1333).
    """
    titles: set[str] = set()
    lines = text.split("\n")
    # A "##" line inside fenced code is a comment, not a body heading, so
    # it must not count as a match for a TOC entry.
    for line, code in zip(lines, fenced_lines(lines)):
        if code:
            continue
        level = len(line) - len(line.lstrip("#"))
        if level in (2, 3) and line[level : level + 1] in (" ", "\t"):
            title = line[level:].strip()
            if title:
                titles.add(title.lower())
    return titles


def dedupe_toc_block(text: str, options: "PipelineOptions") -> str:
    """T4: Strip leading TOC block when its entries mirror later headings.

    Aggressive/maximum profiles only.
    """
    if options.profile == "conservative":
        return text

    lines = text.split("\n")
    fenced = fenced_lines(lines)
    # Find the longest run of consecutive TOC-shaped lines starting near
    # the top. Fenced code ends the run: numbered code lines look like
    # TOC entries.
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    end = start
    while (
        end < len(lines)
        and not fenced[end]
        and (lines[end].strip() == "" or _toc_title(lines[end]) is not None)
    ):
        end += 1

    toc_lines = [ln.strip() for ln in lines[start:end] if _toc_title(ln) is not None]
    if len(toc_lines) < 5:
        return text

    # Extract title-only fragments from the TOC entries
    toc_titles = set()
    for ln in toc_lines:
        title = _toc_title(ln)
        if title:
            toc_titles.add(title.lower())

    # Find body H2/H3 titles AFTER the TOC block
    body = "\n".join(lines[end:])
    body_titles = _body_heading_titles(body)

    if not toc_titles:
        return text
    overlap = len(toc_titles & body_titles) / len(toc_titles)
    if overlap < 0.7:
        return text

    # Strip the TOC block
    return "\n".join(lines[end:]).lstrip("\n")


_LEADER_DOT_RE = re.compile(r"\.{3,}.*$")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")


def _split_table_cells(line: str) -> list[str]:
    """Split a table row into cell text values (no leading/trailing pipes)."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [c.strip() for c in stripped.split("|")]


def dedupe_toc_table(text: str, options: "PipelineOptions") -> str:
    """T7: Strip leading table-formatted TOC when entries mirror later headings.

    Aggressive/maximum profiles only. Only acts on tables in the first 30%
    of the document.
    """
    if options.profile not in ("aggressive", "maximum"):
        return text

    lines = text.split("\n")
    if not lines:
        return text

    cutoff = max(1, int(len(lines) * 0.3))
    # A table inside fenced code is an example, not the document's TOC.
    fenced = fenced_lines(lines)

    # Find first table block within the first 30% of the doc.
    i = 0
    while i < cutoff:
        if not fenced[i] and _TABLE_ROW_RE.match(lines[i]):
            tbl_start = i
            j = i
            while j < len(lines) and not fenced[j] and _TABLE_ROW_RE.match(lines[j]):
                j += 1
            tbl_end = j  # exclusive

            # Need at least 4 data rows (besides header + separator).
            block = lines[tbl_start:tbl_end]
            if len(block) < 6:  # header + sep + 4 rows minimum
                i = tbl_end if tbl_end > i else i + 1
                continue

            # Identify the separator row (often row index 1).
            data_rows = []
            for row in block:
                if _TABLE_SEP_RE.match(row):
                    continue
                data_rows.append(row)
            # First data row is treated as header; remaining are entries.
            if len(data_rows) < 5:
                i = tbl_end if tbl_end > i else i + 1
                continue
            entry_rows = data_rows[1:]
            if len(entry_rows) < 4:
                i = tbl_end if tbl_end > i else i + 1
                continue

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
            if not toc_titles:
                i = tbl_end if tbl_end > i else i + 1
                continue

            # Compare to H2/H3 headings AFTER the table.
            body_after = "\n".join(lines[tbl_end:])
            body_titles = _body_heading_titles(body_after)
            overlap = len(toc_titles & body_titles) / len(toc_titles)
            if overlap >= 0.7:
                # Drop the entire table block (keep surrounding blank line cleanup).
                new_lines = lines[:tbl_start] + lines[tbl_end:]
                # Trim a single leading blank if it now sits between two blanks.
                return "\n".join(new_lines)
            i = tbl_end if tbl_end > i else i + 1
            continue
        i += 1
    return text


_PAGE_NUM_RE = re.compile(r"^Page \d+ of \d+\s*$")
_BARE_NUM_RE = re.compile(r"^\d+\s*$")


def _is_page_number_line(line: str) -> bool:
    """Heuristic: line is a page number / page-N-of-M footer."""
    return bool(_PAGE_NUM_RE.match(line) or _BARE_NUM_RE.match(line))


def strip_running_headers_footers(text: str, _options: "PipelineOptions") -> str:
    """T5: Remove lines that appear ≥3× across page boundaries.

    Also strips "Page N of M" / bare-number footer patterns when they
    appear on ≥3 pages (treated as a class, not by exact match).
    """
    if "\f" not in text:
        return text

    pages = text.split("\f")
    if len(pages) < 3:
        return text

    # Fence flags are per "\n" line, and a "\f" sits inside one such line.
    # Each page after the first starts on the line that holds its "\f",
    # so the line index advances only on a "\n" within a page.
    fenced = fenced_lines(text.split("\n"))
    page_lines: list[list[tuple[str, bool]]] = []
    g = 0
    for page in pages:
        tagged = []
        for j, ln in enumerate(page.split("\n")):
            if j:
                g += 1
            tagged.append((ln, fenced[g]))
        page_lines.append(tagged)

    # Count exact-match candidates (first/last non-empty line of each page).
    # Fenced code is never a running header or footer.
    candidate_counts: dict[str, int] = {}
    page_number_pages = 0
    for tagged in page_lines:
        plines = [ln.strip() for ln, code in tagged if ln.strip() and not code]
        if plines:
            candidate_counts[plines[0]] = candidate_counts.get(plines[0], 0) + 1
            if len(plines) > 1:
                candidate_counts[plines[-1]] = candidate_counts.get(plines[-1], 0) + 1
        # Count pages that contain a page-number-style line
        if any(_is_page_number_line(ln) for ln in plines):
            page_number_pages += 1

    repeated = {ln for ln, count in candidate_counts.items() if count >= 3}
    strip_page_numbers = page_number_pages >= 3
    if not repeated and not strip_page_numbers:
        return text

    out_pages: list[str] = []
    for tagged in page_lines:
        kept = []
        for ln, code in tagged:
            stripped = ln.strip()
            if code:
                kept.append(ln)
                continue
            if stripped in repeated:
                continue
            if strip_page_numbers and _is_page_number_line(stripped):
                continue
            kept.append(ln)
        out_pages.append("\n".join(kept))
    return "\f".join(out_pages)


_ORPHAN_PUNCT_RE = re.compile(r"^\s*[|>]+\s*$")
_TERMINAL_PUNCT_RE = re.compile(r"[.!?:;]$")
_HEADING_OR_KNOWN_SHORT_RE = re.compile(
    r"^(Contents|References|Appendix|Notes|Note:|Index|Glossary|"
    r"Acknowledgments|Abstract|Summary)\s*$",
    re.IGNORECASE,
)


def strip_orphan_punctuation(text: str, options: "PipelineOptions") -> str:
    """Drop lines containing only ``|`` or ``>``. Lane-agnostic.

    Splits cleanly out of T10 in v1.0.3 so the structured (Docling) lane
    can also remove malformed table-row remnants. The trafilatura
    short-fragment heuristic stays in ``strip_web_fragments`` and only
    runs on the text lane.
    """
    if options.profile not in ("aggressive", "maximum"):
        return text
    lines = text.split("\n")
    return "\n".join(
        ln
        for ln, code in zip(lines, fenced_lines(lines))
        if code or not _ORPHAN_PUNCT_RE.match(ln)
    )


def strip_web_fragments(text: str, options: "PipelineOptions") -> str:
    """T10: Drop trafilatura extraction fragments (orphan chars, incomplete sentences)."""
    if options.profile not in ("aggressive", "maximum"):
        return text
    text = strip_orphan_punctuation(text, options)
    lines = text.split("\n")
    fenced = fenced_lines(lines)
    out: list[str] = []
    n = len(lines)
    # Last non-blank source line before the current one. The v1.0.2 spec
    # (section 5.5) drops a short line only when the text before it ended
    # a sentence, since that is the shape of a fragment trafilatura cut
    # from the start of a new paragraph. Without that check the stage
    # dropped a plain-text title on line one and any short line after a
    # heading, with no warning.
    prev_text = ""
    for i, line in enumerate(lines):
        stripped = line.strip()
        follows_sentence = bool(
            prev_text
            and not prev_text.startswith("#")
            and _TERMINAL_PUNCT_RE.search(prev_text)
        )
        if stripped:
            prev_text = stripped
        # Short incomplete sentence between blank lines
        if (
            follows_sentence
            and not fenced[i]
            and stripped
            and len(stripped) <= 25
            and not _TERMINAL_PUNCT_RE.search(stripped)
            and not _HEADING_OR_KNOWN_SHORT_RE.match(stripped)
            and not stripped.startswith("#")
            and not stripped.startswith("-")
            and not stripped.startswith("|")
            and (i == 0 or not lines[i - 1].strip())
            and (i == n - 1 or not lines[i + 1].strip())
        ):
            continue
        out.append(line)
    return "\n".join(out)


def restore_lists_and_code(text: str, _options: "PipelineOptions") -> str:
    """T6: Wrap ≥4-line indented blocks (4 spaces or tab) in fenced code.

    Conservative — only acts when block sits between blank lines and is
    not already inside a fence.
    """
    lines = text.split("\n")
    fenced = fenced_lines(lines)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if fenced[i]:
            out.append(line)
            i += 1
            continue

        # Look for a run of indented lines (4+ leading spaces)
        if line.startswith("    ") and (i == 0 or lines[i - 1].strip() == ""):
            run_start = i
            while (
                i < len(lines)
                and not fenced[i]
                and (lines[i].startswith("    ") or lines[i] == "")
            ):
                i += 1
            run = lines[run_start:i]
            non_empty = [r for r in run if r.strip()]
            if len(non_empty) >= 4:
                # Strip the leading 4 spaces and wrap in a fence
                out.append("```")
                for r in run:
                    if r.startswith("    "):
                        out.append(r[4:])
                    else:
                        out.append(r)
                out.append("```")
                continue
            else:
                out.extend(run)
                continue
        out.append(line)
        i += 1
    return "\n".join(out)


_COVER_KEYWORDS = re.compile(
    r"qr code|scan the|customer feedback form|please share your feedback",
    re.IGNORECASE,
)
_EDITION_RE = re.compile(
    r"^(?:[A-Z][a-z]+|\d+(?:st|nd|rd|th))\s+edition\s+\d{4}-\d{2}\s*$"
)
_CORRECTED_RE = re.compile(r"^Corrected version \d{4}-\d{2}\s*$")
_FIRST_H2_RE = re.compile(r"^## ")


def strip_cover_artifacts(text: str, options: "PipelineOptions") -> str:
    """T8: Drop cover-page noise (QR blurbs, version stamps) in first 30 lines."""
    if options.profile not in ("aggressive", "maximum"):
        return text
    lines = text.split("\n")
    fenced = fenced_lines(lines)
    out: list[str] = []
    seen_h2 = False
    for i, line in enumerate(lines):
        if fenced[i]:
            out.append(line)
            continue
        if _FIRST_H2_RE.match(line):
            seen_h2 = True
        if seen_h2 or i > 30:
            out.append(line)
            continue
        if (
            _COVER_KEYWORDS.search(line)
            or _EDITION_RE.match(line)
            or _CORRECTED_RE.match(line)
        ):
            continue
        out.append(line)
    return "\n".join(out)


STAGES: list[Stage] = [
    # T2 must see the raw "word-\nword" breaks, so it runs before T1 joins
    # wrapped lines. The reverse order disabled T2 entirely before v1.2.1.
    dehyphenate,
    repair_line_wraps,
    strip_repeated_byline,
    dedupe_paragraphs,
    dedupe_toc_block,
    dedupe_toc_table,
    strip_running_headers_footers,
    strip_web_fragments,
    restore_lists_and_code,
    strip_cover_artifacts,
]
