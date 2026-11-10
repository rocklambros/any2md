"""Structured-lane pipeline stages.

Phase 2: S1-S4 implemented. Stages run BEFORE shared cleanup on Docling-
emitted markdown — they trust Docling's layout decisions and only normalize
representational details.
"""

from __future__ import annotations

import re
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from any2md.pipeline import PipelineOptions

Stage = Callable[[str, "PipelineOptions"], str]

# Alt text stops at the next unescaped bracket (escaped ``\[`` stays in
# it) and the URL is length-bounded, so a run of "![" with no "]" is
# rejected in linear time (CWE-1333).
_IMG_LINK_RE = re.compile(r"!\[((?:[^\[\]\\]|\\[\s\S])*)\]\(([^)\n]{1,2048})\)")
_FIGURE_OPEN_RE = re.compile(r"<figure\b", re.IGNORECASE)
_FIGURE_CLOSE_RE = re.compile(r"</figure\s*>", re.IGNORECASE)
_FIGCAPTION_OPEN_RE = re.compile(r"<figcaption\b", re.IGNORECASE)
_FIGCAPTION_CLOSE_RE = re.compile(r"</figcaption\s*>", re.IGNORECASE)
# A tag may not contain "<", so a run of "<" with no ">" fails per start in
# constant time instead of rescanning to the end (CWE-1333).
_TAG_RE = re.compile(r"<[^<>]+>")


def _figure_caption(inner: str) -> str | None:
    """Raw caption markup inside one figure, or None when it has none."""
    start = _FIGCAPTION_OPEN_RE.search(inner)
    if not start:
        return None
    tag_end = inner.find(">", start.end())
    if tag_end == -1:
        return None
    close = _FIGCAPTION_CLOSE_RE.search(inner, tag_end + 1)
    if not close:
        return None
    return inner[tag_end + 1 : close.start()]


def _replace_figures(text: str, repl) -> str:
    """Replace each ``<figure>...</figure>`` holding a figcaption via ``repl``.

    A single forward scan. The earlier lazy-DOTALL regex rescanned the rest
    of the document from every unclosed ``<figure>``, which is quadratic
    (CWE-1333). Each search here starts where the previous one ended. A
    figure without a figcaption is left unchanged; the old regex could
    instead run on into a later figure's caption.
    """
    out: list[str] = []
    pos = 0
    while True:
        opened = _FIGURE_OPEN_RE.search(text, pos)
        if not opened:
            break
        tag_end = text.find(">", opened.end())
        if tag_end == -1:
            break
        closed = _FIGURE_CLOSE_RE.search(text, tag_end + 1)
        if not closed:
            break
        caption = _figure_caption(text[tag_end + 1 : closed.start()])
        out.append(text[pos : opened.start()])
        if caption is None:
            out.append(text[opened.start() : closed.end()])
        else:
            out.append(repl(caption))
        pos = closed.end()
    out.append(text[pos:])
    return "".join(out)


_IMAGE_PLACEHOLDER_RE = re.compile(r"<!--\s*image\s*-->", re.IGNORECASE)


def lift_figure_captions(text: str, options: "PipelineOptions") -> str:
    """S1: Convert image markdown / <figure> blocks to italic *Figure: caption* lines.

    Drops image references unless --save-images is set.
    """

    def _img_repl(match: re.Match[str]) -> str:
        alt = match.group(1).strip()
        url = match.group(2).strip()
        caption_line = f"*Figure: {alt}*" if alt else ""
        if options.save_images:
            # Keep the link below the caption
            return (
                f"{caption_line}\n\n![{alt}]({url})"
                if caption_line
                else f"![{alt}]({url})"
            )
        return caption_line

    text = _IMG_LINK_RE.sub(_img_repl, text)

    def _figure_repl(caption_markup: str) -> str:
        cap = _TAG_RE.sub("", caption_markup).strip()
        return f"*Figure: {cap}*" if cap else ""

    text = _replace_figures(text, _figure_repl)

    text = _IMAGE_PLACEHOLDER_RE.sub("", text)

    return text


STAGES: list[Stage] = [
    lift_figure_captions,
]


_TABLE_ROW_RE = re.compile(r"^\|.*\|\s*$")
_ALIGNMENT_ROW_RE = re.compile(r"^\|[\s:|-]+\|\s*$")


def compact_tables(text: str, _options: "PipelineOptions") -> str:
    """S2: Strip per-cell padding spaces in GFM tables. Skip alignment row."""
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        # Only act on lines that look like a table row
        if _TABLE_ROW_RE.match(line) and not _ALIGNMENT_ROW_RE.match(line):
            cells = line.split("|")
            # First and last entries are empty (line starts/ends with |)
            cells = [c.strip() for c in cells]
            # Reconstruct without padding
            line = "|" + "|".join(c if c == "" else f" {c} " for c in cells[1:-1]) + "|"
            # Compact spaces inside each cell wrapper to single
            line = re.sub(r"  +", " ", line)
        out.append(line)
    return "\n".join(out)


STAGES.append(compact_tables)


_CITE_GAP_RE = re.compile(r"(\[\d+\])\s+(?=\[\d+\])")


def normalize_citations(text: str, _options: "PipelineOptions") -> str:
    """S3: Coalesce '[1] [2] [3]' → '[1][2][3]' (numeric only)."""
    return _CITE_GAP_RE.sub(r"\1", text)


STAGES.append(normalize_citations)


# Greedy capture to end of line, trailing spaces stripped in Python. The
# earlier lazy ``(.+?)[ \\t]*$`` was quadratic on a long space run (CWE-1333).
_HEADING_LINE_RE = re.compile(r"^(#{1,6})[ \t]+(\S.*)$", re.MULTILINE)


def rank_heading_levels(levels: list[int]) -> list[int]:
    """Re-rank heading levels so none skips a level below its parent.

    Each heading's output level is its depth in a stack of the original
    levels of the sections still open above it. Siblings stay siblings
    and nesting is kept: ``1, 3, 3, 4, 3`` becomes ``1, 2, 2, 3, 2``.
    An H1 resets the stack and stays H1. Nothing is promoted to H1.
    Shared by structured-lane S4 and the HTML converter so both lanes
    rank headings the same way.
    """
    stack: list[int] = [1]  # original levels of open sections, H1 at bottom
    ranked: list[int] = []
    for level in levels:
        if level == 1:
            stack = [1]
            ranked.append(1)
            continue
        while len(stack) > 1 and stack[-1] >= level:
            stack.pop()
        stack.append(level)
        ranked.append(len(stack))
    return ranked


def _indent(line: str) -> tuple[int, int]:
    """Return (column, index) of the first non-blank character of ``line``.

    A tab advances to the next multiple of four, as in CommonMark.
    """
    col = 0
    for i, ch in enumerate(line):
        if ch == " ":
            col += 1
        elif ch == "\t":
            col += 4 - col % 4
        else:
            return col, i
    return col, len(line)


def _list_marker(line: str, pos: int, end: int) -> int | None:
    """Return the index just past a list marker at ``line[pos]``, or None.

    Markers are ``-``, ``*``, ``+``, and one to nine digits followed by
    ``.`` or ``)``. A marker must be followed by a space or by the end of
    the line's content (``end``), so ``-x`` and ``1.x`` are paragraph text.
    """
    i = pos
    if line[i] in "-*+":
        i += 1
    else:
        while i < end and i - pos < 9 and "0" <= line[i] <= "9":
            i += 1
        if i == pos or i >= end or line[i] not in ".)":
            return None
        i += 1
    if i < end and line[i] != " ":
        return None
    return i


def _break_starts(line: str) -> list[bool]:
    """Flag each index from which a thematic break runs to the line end.

    A thematic break is three or more of one character from ``-``, ``*``,
    ``_`` with only whitespace between. One backward pass, so checking
    every marker position on a line stays linear.
    """
    starts = [False] * len(line)
    mark = ""  # the one break character seen so far, "x" once disqualified
    count = 0
    for i in range(len(line) - 1, -1, -1):
        ch = line[i]
        if ch in " \t\r":
            continue
        if mark == "":
            mark = ch if ch in "-*_" else "x"
        elif ch != mark:
            mark = "x"
        count += 1
        starts[i] = mark != "x" and count >= 3
    return starts


def _fence_opener(rest: str) -> tuple[str, int] | None:
    """Return (fence character, run length) when ``rest`` opens a fence."""
    ch = rest[:1]
    if ch not in ("`", "~"):
        return None
    run = len(rest) - len(rest.lstrip(ch))
    if run < 3:
        return None
    # CommonMark forbids a backtick in a backtick fence's info string, so
    # such a line is inline code, not a fence.
    if ch == "`" and "`" in rest[run:]:
        return None
    return ch, run


def _fence_closes(rest: str, ch: str, length: int) -> bool:
    """Return True when ``rest`` closes a fence opened with ``ch`` * ``length``."""
    run = len(rest) - len(rest.lstrip(ch))
    return run >= length and not rest[run:].strip()


def fenced_lines(lines: list[str]) -> list[bool]:
    """Flag each line that belongs to a fenced code block, fences included.

    Follows the CommonMark fence rules that decide whether a ``#`` line
    is code:

    - A fence opens with three or more backticks or tildes and closes
      only on a run of the same character at least as long, followed by
      nothing but whitespace. A backtick opener's info string may not
      hold a backtick.
    - An opener or closer may sit at most three columns past its base:
      column 0 at top level, or the content column of the enclosing list
      item. Deeper indentation is indented code, not a fence.
    - An unclosed top-level fence runs to the end of the text. A fence
      inside a list item also ends when the item ends: a non-blank line
      left of the item's content column closes the fence and is then
      read as an ordinary line.
    - A thematic break (``* * *``, ``- - -``, ``___``) is never a list
      item, and one line may open several items (``- - ```` or
      ``1. - ````). Every marker is consumed before the fence test.

    List items are tracked with a stack of content columns, so nested
    items work. Lazy continuation lines and block quotes are not
    modeled: a non-blank line left of the item's content column ends the
    item. One pass, linear in the input length. Shared by structured-lane
    S4 and the HTML converter so both lanes agree on what is code.
    """
    flags: list[bool] = []
    fence: tuple[str, int, int] | None = None  # (char, run length, base column)
    list_cols: list[int] = []  # content columns of open list items
    for line in lines:
        col, idx = _indent(line)
        rest = line[idx:]
        if fence is not None:
            ch, length, base = fence
            # Base 0 is a top-level fence, which only a closer can end.
            if base > 0 and rest.strip() and col < base:
                fence = None  # the list item ended, so its fence did too
            else:
                flags.append(True)
                if col - base <= 3 and _fence_closes(rest, ch, length):
                    fence = None
                continue
        if not rest.strip():
            flags.append(False)  # blank lines keep list items open
            continue
        while list_cols and col < list_cols[-1]:
            list_cols.pop()
        base = list_cols[-1] if list_cols else 0
        flags.append(False)
        if col - base > 3:
            continue  # indented code
        # Consume every list marker on the line, tracking positions by
        # index so a long run of markers stays linear. Each marker makes
        # its item's content column the base for the rest of the line.
        end = len(line.rstrip())
        breaks: list[bool] | None = None
        pos = idx
        while pos < end:
            if line[pos] in "-*_":
                if breaks is None:
                    breaks = _break_starts(line)
                if breaks[pos]:
                    pos = end  # thematic break, never a list item or fence
                    break
            after = _list_marker(line, pos, end)
            if after is None:
                break
            marker_col = col + after - pos
            nxt = after
            while nxt < end and line[nxt] == " ":
                nxt += 1
            spaces = nxt - after
            # An empty item, or five or more spaces (indented code inside
            # the item), puts the content column one space past the marker.
            base = marker_col + (spaces if 0 < spaces <= 4 and nxt < end else 1)
            list_cols.append(base)
            col, pos = marker_col + spaces, nxt
            if col - base > 3:
                break  # indented code inside the item holds no marker
        if pos >= end or col - base > 3:
            continue
        opener = _fence_opener(line[pos:end])
        if opener is not None:
            fence = (opener[0], opener[1], base)
            flags[-1] = True
    return flags


def _fenced_line_starts(text: str) -> set[int]:
    """Return the offsets of every line that ``fenced_lines`` flags."""
    starts: set[int] = set()
    offset = 0
    lines = text.split("\n")
    for line, fenced in zip(lines, fenced_lines(lines)):
        if fenced:
            starts.add(offset)
        offset += len(line) + 1
    return starts


def enforce_heading_hierarchy(text: str, _options: "PipelineOptions") -> str:
    """S4: Ensure single H1 and no skipped levels.

    - If no H1 exists, the first heading is promoted to H1.
    - Subsequent H1s are demoted to H2.
    - Remaining levels are ranked with ``rank_heading_levels``: each
      heading sits one level below its nearest shallower ancestor, so
      sibling H3s under an H1 all become H2.
    - Lines inside fenced code blocks are never treated as headings.
    """
    fenced = _fenced_line_starts(text)
    matches = [m for m in _HEADING_LINE_RE.finditer(text) if m.start() not in fenced]
    if not matches:
        return text

    # Pass 1: collect (level, title, span)
    levels = [len(m.group(1)) for m in matches]

    # Promote first heading to H1 if no H1
    if 1 not in levels:
        levels[0] = 1

    # Demote subsequent H1s
    seen_h1 = False
    for i, lvl in enumerate(levels):
        if lvl == 1:
            if seen_h1:
                levels[i] = 2
            else:
                seen_h1 = True

    # Ranking after the H1 fixes above means demoted H1s act as H2
    # section parents and their skipped children nest under them.
    levels = rank_heading_levels(levels)

    # Pass 2: rewrite
    out = []
    last = 0
    for new_level, m in zip(levels, matches):
        out.append(text[last : m.start()])
        out.append("#" * new_level + " " + m.group(2).rstrip())
        last = m.end()
    out.append(text[last:])
    return "".join(out)


STAGES.append(enforce_heading_hierarchy)


# Lane-agnostic body-cleanup stages (also run on structured lane in
# v1.0.3+). T7/T8/T9 were originally text-lane-only in v1.0.2, but the
# patterns they catch ("Author's Contact Information:" duplicate, leading
# TOC tables, cover-page artifacts) appear in Docling output too — these
# stages should fire regardless of which extractor produced the markdown.
# strip_orphan_punctuation (the lone-|/> portion of T10) is also added
# here in v1.0.3 because Docling's table parser occasionally emits
# malformed rows. The remaining T10 short-fragment heuristic stays
# text-lane-only (trafilatura-specific).
from any2md.pipeline.text import (  # noqa: E402 — late import after STAGES init
    dedupe_toc_table,
    strip_cover_artifacts,
    strip_orphan_punctuation,
    strip_repeated_byline,
)

STAGES.extend(
    [
        strip_repeated_byline,
        dedupe_toc_table,
        strip_cover_artifacts,
        strip_orphan_punctuation,
    ]
)
