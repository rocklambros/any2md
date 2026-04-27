"""Text-lane pipeline stages.

Phase 3: T1-T6 implemented. These stages run on text-lane output (mammoth
fallback, pymupdf4llm fallback, trafilatura, TXT structurizer) BEFORE the
shared cleanup pipeline. They repair regression artifacts that those
backends leave behind.
"""

from __future__ import annotations

import re
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from any2md.pipeline import PipelineOptions

Stage = Callable[[str, "PipelineOptions"], str]


_TERMINAL_PUNCT = ".!?:"
_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*+]|\d+\.|[a-z]\.)\s+", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,6}\s")
_TABLE_RE = re.compile(r"^\s*\|")
_FENCE_RE = re.compile(r"^\s*```")


def _is_structural(line: str) -> bool:
    """A 'structural' line — never join into or out of."""
    return bool(
        _LIST_PREFIX_RE.match(line)
        or _HEADING_RE.match(line)
        or _TABLE_RE.match(line)
        or _FENCE_RE.match(line)
    )


def repair_line_wraps(text: str, _options: "PipelineOptions") -> str:
    """T1: Join lines that look like soft wraps inside paragraphs."""
    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        # Track fenced code state — never join inside.
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if in_fence:
            out.append(line)
            i += 1
            continue

        # End-of-text or empty line: emit and continue
        if i == len(lines) - 1 or line == "":
            out.append(line)
            i += 1
            continue

        next_line = lines[i + 1]
        # Stop conditions: structural next line, blank next line, terminal
        # punctuation at end of current line, uppercase start of next line.
        if (
            next_line == ""
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


_HYPHEN_WRAP_RE = re.compile(r"([a-z]+)-\n([a-z]+)")


def dehyphenate(text: str, _options: "PipelineOptions") -> str:
    """T2: Merge soft-hyphenated word breaks across line ends.

    Conservative — only merges when the joined word appears elsewhere
    (same-doc corroboration). Avoids breaking compound words like
    'co-pilot' that appear hyphenated genuinely.
    """
    # Find candidates first
    candidates = list(_HYPHEN_WRAP_RE.finditer(text))
    if not candidates:
        return text

    # Build set of words that appear in the text (lowercase, alphanumeric)
    words_in_doc = set(re.findall(r"\b[a-z]+\b", text.lower()))

    def _replace(match: re.Match[str]) -> str:
        prefix_word = match.group(1)
        suffix_word = match.group(2)
        # The full word that would result if we merge
        joined = prefix_word + suffix_word
        # Look up: does the joined-form appear elsewhere in the doc?
        if joined.lower() in words_in_doc:
            return prefix_word + suffix_word
        return match.group(0)  # keep hyphen + newline

    return _HYPHEN_WRAP_RE.sub(_replace, text)


_AUTHOR_CONTACT_RE = re.compile(
    r"^Author(?:'s|s'?)\s*Contact Information:.*$",
    re.IGNORECASE,
)
_CONTACT_EMAIL_RE = re.compile(r"^Contact:.*@.*\..*$", re.IGNORECASE)


def strip_repeated_byline(text: str, options: "PipelineOptions") -> str:
    """T9: Remove 'Author's Contact Information:' duplicate-byline lines."""
    if options.profile not in ("aggressive", "maximum"):
        return text
    lines = text.split("\n")
    out: list[str] = []
    for i, line in enumerate(lines):
        if _AUTHOR_CONTACT_RE.match(line):
            continue
        if i < 50 and _CONTACT_EMAIL_RE.match(line):
            continue
        out.append(line)
    return "\n".join(out)


_PARA_SPLIT_RE = re.compile(r"\n\s*\n")


def dedupe_paragraphs(text: str, _options: "PipelineOptions") -> str:
    """T3: Drop a paragraph identical to the immediately previous one."""
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


_TOC_LINE_RE = re.compile(r"^\s*(?:[\d.]+\s+)?(.+?)(?:\s*\.{3,}|\s+)\s*\d+\s*$")
_BODY_HEADING_RE = re.compile(r"^#{2,3}\s+(.+?)\s*$", re.MULTILINE)


def dedupe_toc_block(text: str, options: "PipelineOptions") -> str:
    """T4: Strip leading TOC block when its entries mirror later headings.

    Aggressive/maximum profiles only.
    """
    if options.profile == "conservative":
        return text

    lines = text.split("\n")
    # Find the longest run of consecutive TOC-shaped lines starting near the top
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    end = start
    while end < len(lines) and (
        lines[end].strip() == "" or _TOC_LINE_RE.match(lines[end])
    ):
        end += 1

    toc_lines = [ln.strip() for ln in lines[start:end] if _TOC_LINE_RE.match(ln)]
    if len(toc_lines) < 5:
        return text

    # Extract title-only fragments from the TOC entries
    toc_titles = set()
    for ln in toc_lines:
        m = _TOC_LINE_RE.match(ln)
        if m:
            toc_titles.add(m.group(1).strip().lower())

    # Find body H2/H3 titles AFTER the TOC block
    body = "\n".join(lines[end:])
    body_titles = {m.group(1).strip().lower() for m in _BODY_HEADING_RE.finditer(body)}

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

    # Find first table block within the first 30% of the doc.
    i = 0
    while i < cutoff:
        if _TABLE_ROW_RE.match(lines[i]):
            tbl_start = i
            j = i
            while j < len(lines) and _TABLE_ROW_RE.match(lines[j]):
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
            body_titles = {
                m.group(1).strip().lower()
                for m in _BODY_HEADING_RE.finditer(body_after)
            }
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

    # Count exact-match candidates (first/last non-empty line of each page)
    candidate_counts: dict[str, int] = {}
    page_number_pages = 0
    for page in pages:
        plines = [ln.strip() for ln in page.split("\n") if ln.strip()]
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
    for page in pages:
        kept = []
        for ln in page.split("\n"):
            stripped = ln.strip()
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
    return "\n".join(ln for ln in text.split("\n") if not _ORPHAN_PUNCT_RE.match(ln))


def strip_web_fragments(text: str, options: "PipelineOptions") -> str:
    """T10: Drop trafilatura extraction fragments (orphan chars, incomplete sentences)."""
    if options.profile not in ("aggressive", "maximum"):
        return text
    text = strip_orphan_punctuation(text, options)
    lines = text.split("\n")
    out: list[str] = []
    n = len(lines)
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Short incomplete sentence between blank lines
        if (
            stripped
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
    out: list[str] = []
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if in_fence:
            out.append(line)
            i += 1
            continue

        # Look for a run of indented lines (4+ leading spaces)
        if line.startswith("    ") and (i == 0 or lines[i - 1].strip() == ""):
            run_start = i
            while i < len(lines) and (lines[i].startswith("    ") or lines[i] == ""):
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
    out: list[str] = []
    seen_h2 = False
    for i, line in enumerate(lines):
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
    repair_line_wraps,
    dehyphenate,
    strip_repeated_byline,
    dedupe_paragraphs,
    dedupe_toc_block,
    dedupe_toc_table,
    strip_running_headers_footers,
    strip_web_fragments,
    restore_lists_and_code,
    strip_cover_artifacts,
]
