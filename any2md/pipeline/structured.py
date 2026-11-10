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


def _blank_from(s: str, i: int) -> bool:
    """Return True when ``s[i:]`` holds only spaces, tabs, and a final CR.

    CommonMark treats only spaces and tabs as blank, so other Unicode
    whitespace such as U+00A0 counts as content. A trailing ``\\r`` left
    by CRLF input is allowed at the very end.
    """
    last = len(s) - 1
    for j in range(i, len(s)):
        ch = s[j]
        if ch != " " and ch != "\t" and not (ch == "\r" and j == last):
            return False
    return True


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
    return run >= length and _blank_from(rest, run)


# CommonMark 0.31.2 section 4.6, HTML block start condition 6.
_HTML_BLOCK_TAGS = frozenset(
    "address article aside base basefont blockquote body caption center col"
    " colgroup dd details dialog dir div dl dt fieldset figcaption figure"
    " footer form frame frameset h1 h2 h3 h4 h5 h6 head header hr html iframe"
    " legend li link main menu menuitem nav noframes ol optgroup option p"
    " param search section summary table tbody td tfoot th thead title tr"
    " track ul".split()
)
# Start condition 1. These blocks run to a closing tag, blank lines included.
_HTML_RAW_TAGS = ("pre", "script", "style", "textarea")
_HTML_RAW_ENDS = ("</pre>", "</script>", "</style>", "</textarea>")


def _is_ascii_letter(ch: str) -> bool:
    return "a" <= ch <= "z" or "A" <= ch <= "Z"


def _tag_name_end(s: str, i: int) -> int | None:
    """Return the index past an HTML tag name starting at ``s[i]``, or None."""
    if i >= len(s) or not _is_ascii_letter(s[i]):
        return None
    j = i + 1
    while j < len(s) and (_is_ascii_letter(s[j]) or "0" <= s[j] <= "9" or s[j] == "-"):
        j += 1
    return j


def _complete_tag(s: str) -> tuple[int, str] | None:
    """Parse one open or closing tag at the start of ``s``.

    Returns (index past the tag, tag name) or None. Follows the
    CommonMark raw HTML grammar for tag names, attributes, and quoted or
    unquoted values. Each character is read once, so the parse is linear.
    """
    n = len(s)
    if s.startswith("</"):
        j = _tag_name_end(s, 2)
        if j is None:
            return None
        name = s[2:j]
        while j < n and s[j] in " \t":
            j += 1
        return (j + 1, name) if j < n and s[j] == ">" else None
    j = _tag_name_end(s, 1)
    if j is None:
        return None
    name = s[1:j]
    while True:
        k = j
        while k < n and s[k] in " \t":
            k += 1
        if k < n and s[k] == ">":
            return k + 1, name
        if s.startswith("/>", k):
            return k + 2, name
        if k == j or k >= n:
            return None  # an attribute needs whitespace before it
        if not (_is_ascii_letter(s[k]) or s[k] in "_:"):
            return None
        k += 1
        while k < n and (
            _is_ascii_letter(s[k]) or "0" <= s[k] <= "9" or s[k] in "_.:-"
        ):
            k += 1
        j = k
        m = k
        while m < n and s[m] in " \t":
            m += 1
        if m < n and s[m] == "=":
            m += 1
            while m < n and s[m] in " \t":
                m += 1
            if m >= n:
                return None
            if s[m] in "\"'":
                close = s.find(s[m], m + 1)
                if close == -1:
                    return None
                j = close + 1
            else:
                v = m
                while v < n and s[v] not in " \t\"'=<>`":
                    v += 1
                if v == m:
                    return None
                j = v


def _html_block_start(rest: str, in_paragraph: bool) -> tuple[str, ...] | None:
    """Return the end markers when ``rest`` starts a CommonMark HTML block.

    ``rest`` is the line content from its first non-blank character, with
    trailing whitespace removed. Types 1 to 5 return their lowercase end
    markers. Types 6 and 7 return an empty tuple because a blank line
    ends them. None means no HTML block starts here. Type 7 cannot
    interrupt a paragraph.
    """
    low = rest.lower()
    for name in _HTML_RAW_TAGS:
        k = len(name) + 1
        if low.startswith("<" + name) and (k == len(low) or low[k] in " \t>"):
            return _HTML_RAW_ENDS
    if low.startswith("<!--"):
        return ("-->",)
    if low.startswith("<?"):
        return ("?>",)
    if low.startswith("<![cdata["):
        return ("]]>",)
    if low.startswith("<!") and len(low) > 2 and _is_ascii_letter(low[2]):
        return (">",)
    j = 2 if low.startswith("</") else 1
    k = _tag_name_end(low, j)
    if k is not None and low[j:k] in _HTML_BLOCK_TAGS:
        if k == len(low) or low[k] in " \t>" or low.startswith("/>", k):
            return ()
    if not in_paragraph:
        tag = _complete_tag(low)
        if tag is not None and tag[0] == len(low) and tag[1] not in _HTML_RAW_TAGS:
            return ()
    return None


def _is_atx_heading(rest: str) -> bool:
    run = len(rest) - len(rest.lstrip("#"))
    return 1 <= run <= 6 and (run == len(rest) or rest[run] == " ")


# Line kinds reported by _scan_blocks.
_TEXT, _FENCE, _HTML = 0, 1, 2


def fenced_lines(lines: list[str]) -> list[bool]:
    """Flag each line that belongs to a fenced code block, fences included."""
    return [kind == _FENCE for kind in _scan_blocks(lines)]


def protected_lines(lines: list[str]) -> list[bool]:
    """Flag each line where a ``#`` is never a heading.

    That is every line of a fenced code block or a raw HTML block. Both
    heading passes (S4 and the HTML converter) skip these lines.
    """
    return [kind != _TEXT for kind in _scan_blocks(lines)]


def _scan_blocks(lines: list[str]) -> list[int]:
    """Classify each line as text, fenced code, or raw HTML block.

    Returns ``_TEXT``, ``_FENCE``, or ``_HTML`` per line. Fence lines
    and HTML block start and end lines count as part of their block.
    Models the CommonMark block rules that decide whether a ``#`` line
    is a heading:

    - Tabs expand to 4-column stops in a working copy of each line before
      indents and list markers are measured. The input is not changed.
    - A fence opens with three or more backticks or tildes and closes
      only on a run of the same character at least as long, followed by
      nothing but spaces or tabs (and a final ``\\r`` from CRLF input). A
      backtick opener's info string may not hold a backtick.
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
    - A list item may interrupt a paragraph only when it is not empty
      and, if ordered, starts at 1. Otherwise the line is paragraph text.
    - Raw HTML blocks (CommonMark 4.6 types 1 to 7) hide fence lines
      and headings. An ATX heading line never starts one.
      Types 1 to 5 end at their end marker, types 6 and 7 at a blank
      line, and type 7 cannot interrupt a paragraph. HTML blocks may
      start inside list items and end when the item ends.

    List items are tracked with a stack of content columns, so nested
    items work. Lazy continuation lines and block quotes are not
    modeled: a non-blank line left of the item's content column ends the
    item. Setext underlines are read as paragraph text or thematic
    breaks. One pass, linear in the input length. Shared by
    structured-lane S4 and the HTML converter so both lanes agree on
    what is code or raw HTML.
    """
    kinds: list[int] = []
    fence: tuple[str, int, int] | None = None  # (char, run length, base column)
    html: tuple[tuple[str, ...], int] | None = None  # (end markers, base column)
    list_cols: list[int] = []  # content columns of open list items
    in_paragraph = False  # the previous line was paragraph text
    for line in lines:
        # After expansion every index equals its CommonMark column.
        work = line.expandtabs(4)
        blank = _blank_from(work, 0)
        col = len(work) - len(work.lstrip(" "))
        if fence is not None:
            ch, length, base = fence
            # Base 0 is a top-level fence, which only a closer can end.
            if base > 0 and not blank and col < base:
                fence = None  # the list item ended, so its fence did too
            else:
                kinds.append(_FENCE)
                if col - base <= 3 and _fence_closes(work[col:], ch, length):
                    fence = None
                continue
        if html is not None:
            ends, base = html
            if base > 0 and not blank and col < base:
                html = None  # the list item ended, so its HTML block did too
            elif not ends and blank:
                # The blank line ends a type 6 or 7 block and is not part
                # of it, so it falls through as an ordinary blank line.
                html = None
            else:
                kinds.append(_HTML)
                if ends and any(e in work.lower() for e in ends):
                    html = None
                continue
        kinds.append(_TEXT)
        if blank:
            in_paragraph = False
            continue
        while list_cols and col < list_cols[-1]:
            list_cols.pop()
        base = list_cols[-1] if list_cols else 0
        if col - base > 3:
            # Indented code, or paragraph continuation text when a
            # paragraph is open. Either way in_paragraph keeps its value.
            continue
        # Consume every list marker on the line, tracking positions by
        # index so a long run of markers stays linear. Each marker makes
        # its item's content column the base for the rest of the line.
        end = len(work.rstrip(" \t\r"))
        breaks: list[bool] | None = None
        pos = col
        is_break = False
        continuation = False
        while pos < end:
            if work[pos] in "-*_":
                if breaks is None:
                    breaks = _break_starts(work)
                if breaks[pos]:
                    is_break = True
                    break
            after = _list_marker(work, pos, end)
            if after is None:
                break
            nxt = after
            while nxt < end and work[nxt] == " ":
                nxt += 1
            empty = nxt >= end
            ordered = work[pos] not in "-*+"
            if in_paragraph and (
                empty or (ordered and int(work[pos : after - 1]) != 1)
            ):
                continuation = True  # this item may not interrupt a paragraph
                break
            in_paragraph = False
            spaces = nxt - after
            # An empty item, or five or more spaces (indented code inside
            # the item), puts the content column one space past the marker.
            base = after + (spaces if 0 < spaces <= 4 and not empty else 1)
            list_cols.append(base)
            pos = nxt
            if pos - base > 3:
                break  # indented code inside the item holds no marker
        if continuation:
            continue  # paragraph text, in_paragraph stays True
        if is_break or pos >= end or pos - base > 3:
            in_paragraph = False
            continue
        rest = work[pos:end]
        opener = _fence_opener(rest)
        if opener is not None:
            fence = (opener[0], opener[1], base)
            kinds[-1] = _FENCE
            in_paragraph = False
            continue
        if rest[0] == "<":
            ends = _html_block_start(rest, in_paragraph)
            if ends is not None:
                kinds[-1] = _HTML
                # Types 1 to 5 may end on their start line.
                if not ends or not any(e in rest.lower() for e in ends):
                    html = (ends, base)
                in_paragraph = False
                continue
        in_paragraph = not _is_atx_heading(rest)
    return kinds


def _protected_line_starts(text: str) -> set[int]:
    """Return the offsets of every line that ``protected_lines`` flags."""
    starts: set[int] = set()
    offset = 0
    lines = text.split("\n")
    for line, protected in zip(lines, protected_lines(lines)):
        if protected:
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
    - Lines inside fenced code or raw HTML blocks are never treated as
      headings.
    """
    protected = _protected_line_starts(text)
    matches = [m for m in _HEADING_LINE_RE.finditer(text) if m.start() not in protected]
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
