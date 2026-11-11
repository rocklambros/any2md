"""CommonMark block scanner shared by every pipeline lane.

Classifies each line of a Markdown body as text, fenced code, or raw
HTML block, notes which lines sit in a block quote, and finds ATX and
setext headings. The structured-lane S4
stage, the text-lane and shared cleanup stages, and the HTML converter
all read it, so every lane agrees on what is code and what is a heading.

This module imports no other pipeline module. text.py, structured.py,
and cleanup.py all depend on it, and a scanner that lived in one of them
created an import cycle.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Iterator, Sequence
from typing import NamedTuple


def _blank_from(s: str, i: int) -> bool:
    """Return True when ``s[i:]`` holds only spaces, tabs, and a final CR.

    CommonMark treats only spaces and tabs as blank, so other Unicode
    whitespace such as U+00A0 counts as content. A trailing ``\\r`` left
    by CRLF input is allowed as the last character.
    """
    last = len(s) - 1
    for j in range(i, len(s)):
        ch = s[j]
        if ch != " " and ch != "\t" and not (ch == "\r" and j == last):
            return False
    return True


def _list_marker(line: str, pos: int, end: int) -> int | None:
    """Return the index past a list marker at ``line[pos]``, or None.

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


# Line kinds reported by _scan_blocks. _QUOTED is a flag added to the
# others, so a fence line inside a block quote is ``_FENCE | _QUOTED``.
_TEXT, _FENCE, _HTML, _QUOTED = 0, 1, 2, 4

# A block quote on the container stack. A list item stores its width
# instead: its content column minus the column its parent's content
# starts at. The width is relative because a quote prefix may sit at a
# different column on each line, and it is always positive.
_QUOTE = -1

# What the rest of a line starts, after its container prefixes.
(
    _INDENTED,
    _EMPTY,
    _BREAK,
    _SETEXT,
    _CONTINUATION,
    _LEAF,
    _FENCE_START,
    _HTML_START,
    _ATX,
    _PARAGRAPH,
) = range(10)

# A heading as (first line index, last line index, level). An ATX
# heading spans one line. A setext heading spans its paragraph lines and
# its underline.
Heading = tuple[int, int, int]


class _BlockMap(NamedTuple):
    kinds: tuple[int, ...]
    setext: tuple[Heading, ...]
    fenced: tuple[bool, ...]


# Every lane stage asks for the map of the text it was handed, and most
# stages return text equal to their input, so one text-lane run used to
# scan the same body 15 or more times. Keying on the text makes a repeat
# a hash lookup. Two entries cover a stage that also scans a slice of its
# input (T4 and T7 read the body after a TOC). The cache holds whole
# texts, so it stays small to bound memory on large documents. Results
# are tuples, so no caller can change a cached map.
_SCAN_CACHE_SIZE = 2


@functools.lru_cache(maxsize=_SCAN_CACHE_SIZE)
def _scan_text(text: str) -> _BlockMap:
    kinds, setext = _scan_blocks(text.split("\n"))
    return _BlockMap(
        tuple(kinds), tuple(setext), tuple(bool(kind & _FENCE) for kind in kinds)
    )


def fenced_lines(text: str) -> tuple[bool, ...]:
    """Flag each line that belongs to a fenced code block, fences included.

    Lines are the pieces of ``text.split("\\n")``.
    """
    return _scan_text(text).fenced


def fence_runs(fenced: Sequence[bool]) -> Iterator[tuple[bool, int, int]]:
    """Yield ``(is_fenced, start, end)`` for each run of equal fence flags.

    ``end`` is exclusive, and the runs cover every line in order. Stages
    that treat fenced code and prose differently walk these runs, so the
    split into runs lives in one place.
    """
    start = 0
    n = len(fenced)
    for k in range(1, n + 1):
        if k == n or fenced[k] != fenced[start]:
            yield fenced[start], start, k
            start = k


def protected_lines(text: str) -> list[bool]:
    """Flag each line where a ``#`` is never a document heading.

    That is every line of a fenced code block, a raw HTML block, or a
    block quote. A heading inside a quote belongs to the quoted text,
    not to the document outline. find_headings skips these lines, so
    both heading passes (S4 and the HTML converter) follow this one
    rule.
    """
    return [kind != _TEXT for kind in _scan_text(text).kinds]


# Leading form feeds and vertical tabs are zero width, as in _scan_blocks.
_ATX_LINE_RE = re.compile(r"[\f\v]*(#{1,6})[ \t]+\S")


def find_headings(text: str) -> list[Heading]:
    """Return the headings S4 and the HTML lane rank, in document order.

    An ATX heading counts when it starts at column 0 outside fenced
    code, raw HTML, and block quotes. Form feeds and vertical tabs
    before it take no column. A setext heading counts when its
    paragraph sits at the top level. Headings nested in a list item or
    a block quote are left alone, the same rule the ATX pattern applies
    by requiring column 0.
    """
    setext = _scan_text(text).setext
    protected = protected_lines(text)
    lines = text.split("\n")
    headings: list[Heading] = []
    nxt = 0  # the next setext heading not yet passed
    i = 0
    while i < len(lines):
        if nxt < len(setext) and setext[nxt][0] == i:
            headings.append(setext[nxt])
            i = setext[nxt][1] + 1
            nxt += 1
            continue
        if not protected[i]:
            m = _ATX_LINE_RE.match(lines[i])
            if m:
                headings.append((i, i, len(m.group(1))))
        i += 1
    return headings


def setext_text(lines: list[str], heading: Heading) -> str:
    """Return a setext heading's content as the text of one ATX line."""
    first, last, _ = heading
    # A soft line break inside a heading renders as a space. ATX holds
    # one line, so a hard break joins the same way and loses its marker:
    # strip() drops the trailing-spaces form, and _drop_hard_break drops
    # a final unescaped backslash. The last line has no break after it.
    parts = [line.strip(" \t\r\f\v") for line in lines[first:last]]
    parts = [_drop_hard_break(part) for part in parts[:-1]] + parts[-1:]
    text = " ".join(part for part in parts if part)
    head = text.rstrip("#")
    if head != text and head[-1:] in ("", " ", "\t"):
        # In ATX form a final "#" run after a space is a closing
        # sequence and would drop out of the heading text.
        text = head + "\\" + text[len(head) :]
    return text


def _drop_hard_break(part: str) -> str:
    """Remove a backslash hard break from the end of ``part``.

    Only an odd run of trailing backslashes ends in a break. An even run
    is escaped backslashes, which are text.
    """
    run = len(part) - len(part.rstrip("\\"))
    if run % 2:
        return part[:-1].rstrip(" \t")
    return part


# Form feeds and vertical tabs mark page breaks in extracted text. The
# scanner reads them as zero width, so a fence, quote, list marker, or
# heading right after a page break still counts, and a line holding
# only them is blank, the same as Python's str.strip() sees it.
_ZERO_WIDTH = str.maketrans("", "", "\f\v")


def _skip_spaces(s: str, i: int) -> int:
    while i < len(s) and s[i] == " ":
        i += 1
    return i


def _content_end(s: str) -> int:
    """Return the index past the last character ``_blank_from`` counts."""
    end = len(s)
    if end and s[end - 1] == "\r":
        end -= 1
    while end and s[end - 1] in " \t":
        end -= 1
    return end


def _setext_level(s: str, i: int, end: int) -> int:
    """Return 1 or 2 when ``s[i:end]`` is a setext underline, else 0."""
    ch = s[i]
    j = i
    while j < end and s[j] == ch:
        j += 1
    if j < end:
        return 0
    return 1 if ch == "=" else 2


def _scan_blocks(lines: list[str]) -> tuple[list[int], list[Heading]]:
    """Classify each line and find the top-level setext headings.

    Returns one kind per line (``_TEXT``, ``_FENCE``, or ``_HTML``, plus
    the ``_QUOTED`` flag for lines inside a block quote) and the setext
    headings whose paragraph sits outside every container. Fence lines
    and HTML block start and end lines count as part of their block.
    Models the CommonMark block rules that decide whether a ``#`` line
    is a heading:

    - Tabs expand to 4-column stops in a working copy of each line before
      indents and list markers are measured. Form feeds and vertical tabs
      are dropped from that copy first, so a page break before a block
      marker takes no column. The input is not changed.
    - Containers are block quotes and list items, tracked on one stack
      so they nest in any order. A quote line starts with ``>`` after at
      most three spaces, and one space after the ``>`` is part of the
      prefix. A list item continues on a line indented to its content
      column, or on a blank line. A blank line ends a block quote.
    - A fence opens with three or more backticks or tildes and closes
      only on a run of the same character at least as long, followed by
      nothing but spaces or tabs (and a final ``\\r`` from CRLF input). A
      backtick opener's info string may not hold a backtick.
    - An opener or closer may sit at most three columns past its base:
      the column after its container prefixes. Deeper indentation is
      indented code, not a fence.
    - An unclosed top-level fence runs to the end of the text. A fence
      inside a container ends when the container does, and the line
      that ends it is then read as an ordinary line.
    - A thematic break (``* * *``, ``- - -``, ``___``) is never a list
      item, and one line may open several containers (``- - ````,
      ``1. - ````, ``> - > ````). Every marker is consumed before the
      fence test.
    - A list item may interrupt a paragraph only when it is not empty
      and, if ordered, starts at 1. Otherwise the line is paragraph text.
      An item that is still empty ends at the next blank line, since an
      item may not open with a blank line.
    - Lazy continuation: a paragraph line that does not match every open
      container still continues the paragraph, and keeps the containers
      open, unless it starts another block. Lazy lines never continue a
      fence or an HTML block.
    - Setext headings: a ``=`` or ``-`` run (at most three spaces in,
      trailing spaces or tabs allowed) after paragraph text in the same
      container is an underline. It wins over a thematic break and an
      empty list item, and it is never a lazy line. After a blank line,
      ``---`` is a thematic break.
    - Raw HTML blocks (CommonMark 4.6 types 1 to 7) hide fence lines
      and headings. An ATX heading line never starts one.
      Types 1 to 5 end at their end marker, types 6 and 7 at a blank
      line, and type 7 cannot interrupt a paragraph. HTML blocks may
      start inside containers and end when the container ends.

    Not modeled: link reference definitions, which cannot hold a heading
    line. One pass, linear in the input length.
    Shared by structured-lane S4, the text-lane and cleanup stages, and
    the HTML converter so all of them agree on what is code, raw HTML,
    quoted text, or a heading.
    """
    kinds: list[int] = []
    setext: list[Heading] = []
    stack: list[int] = []  # open containers, outermost first
    quote_at: list[int] = []  # stack indices of the open block quotes
    fence: tuple[str, int] | None = None  # (char, run length) of the open fence
    html: tuple[str, ...] | None = None  # end markers of the open HTML block
    in_paragraph = False  # the previous line was paragraph text
    para_start = 0  # index of the open paragraph's first line
    empty_item = -1  # stack index of a list item with no content yet, or -1
    for i, line in enumerate(lines):
        # After expansion every index equals its CommonMark column.
        if "\f" in line or "\v" in line:
            line = line.translate(_ZERO_WIDTH)
        work = line.expandtabs(4)
        size = len(work)
        end = _content_end(work)

        # Match open containers, outermost first. A quote consumes its
        # ">" and each list item consumes its width, so a non-blank line
        # matches at most one container per column. ``ns`` is the first
        # non-space at or after ``pos``, so the spaces of a line are read
        # once however deep the stack is.
        pos = 0
        ns = _skip_spaces(work, 0)
        matched = 0
        quotes_matched = 0
        while matched < len(stack):
            if stack[matched] == _QUOTE:
                if ns - pos > 3 or ns >= size or work[ns] != ">":
                    break
                pos = ns + 1
                if pos < size and work[pos] == " ":
                    pos += 1
                ns = _skip_spaces(work, pos)
                matched += 1
                quotes_matched += 1
            elif ns >= end:
                # A blank rest matches every list item up to the next
                # quote, which it cannot match. Jumping there keeps a
                # blank line O(1) under a deep list.
                if quotes_matched < len(quote_at):
                    matched = quote_at[quotes_matched]
                else:
                    matched = len(stack)
                break
            elif ns - pos >= stack[matched]:
                pos += stack[matched]
                matched += 1
            else:
                break
        blank = ns >= end
        if blank and 0 <= empty_item < matched:
            matched = empty_item
        all_matched = matched == len(stack)

        if fence is not None or html is not None:
            quoted = _QUOTED if quote_at else 0
            if not all_matched:
                # Lazy continuation never extends a fence or HTML block,
                # so the leaf ends with its container.
                fence = html = None
            elif fence is not None:
                kinds.append(_FENCE | quoted)
                if ns - pos <= 3 and _fence_closes(work[ns:], fence[0], fence[1]):
                    fence = None
                continue
            elif not html and blank:
                # The blank line ends a type 6 or 7 block and is not part
                # of it, so it falls through as an ordinary blank line.
                html = None
            else:
                kinds.append(_HTML | quoted)
                if html and any(e in work[pos:].lower() for e in html):
                    html = None
                continue

        if blank:
            del stack[matched:]
            while quote_at and quote_at[-1] >= matched:
                quote_at.pop()
            kinds.append(_QUOTED if quote_at else _TEXT)
            in_paragraph = False
            empty_item = -1
            continue

        # Find what the rest of the line starts. New containers go to
        # ``opened`` first: a lazy line keeps the old stack instead.
        # ``p`` is the column indents count from, ``q`` the first
        # non-space at or after it.
        interrupting = in_paragraph and all_matched
        opened: list[int] = []
        p, q = pos, ns
        breaks: list[bool] | None = None
        level = 0
        while True:
            if q - p > 3:
                result = _INDENTED
                break
            if q >= end:
                result = _EMPTY
                break
            ch = work[q]
            if ch == ">":
                opened.append(_QUOTE)
                p = q + 1
                if p < size and work[p] == " ":
                    p += 1
                q = _skip_spaces(work, p)
                continue
            if ch in "=-" and interrupting and not opened:
                # Checked before thematic breaks and list items, which a
                # setext underline wins over. Only one check runs per
                # line, so a long underline stays linear.
                level = _setext_level(work, q, end)
                if level:
                    result = _SETEXT
                    break
            if ch in "-*_":
                if breaks is None:
                    breaks = _break_starts(work)
                if breaks[q]:
                    result = _BREAK
                    break
            after = _list_marker(work, q, end)
            if after is None:
                result = _LEAF
                break
            nxt = _skip_spaces(work, after)
            empty = nxt >= end
            ordered = work[q] not in "-*+"
            if (
                interrupting
                and not opened
                and (empty or (ordered and int(work[q : after - 1]) != 1))
            ):
                result = _CONTINUATION  # this item may not interrupt a paragraph
                break
            spaces = nxt - after
            # An empty item, or five or more spaces (indented code inside
            # the item), puts the content column one space past the marker.
            content = after + (spaces if 0 < spaces <= 4 and not empty else 1)
            opened.append(content - p)
            p = content
            q = nxt

        ends: tuple[str, ...] | None = None
        opener: tuple[str, int] | None = None
        if result == _LEAF:
            rest = work[q:end]
            opener = _fence_opener(rest)
            if opener is not None:
                result = _FENCE_START
            else:
                if rest[0] == "<":
                    # Type 7 may not interrupt a paragraph, which a lazy
                    # line would otherwise continue.
                    ends = _html_block_start(rest, in_paragraph and not opened)
                if ends is not None:
                    result = _HTML_START
                elif _is_atx_heading(rest):
                    result = _ATX
                else:
                    result = _PARAGRAPH

        if (
            not all_matched
            and in_paragraph
            and not opened
            and result in (_INDENTED, _PARAGRAPH)
        ):
            # Lazy continuation: the line stays in the open paragraph and
            # every container stays open.
            kinds.append(_QUOTED if quote_at else _TEXT)
            empty_item = -1
            continue

        del stack[matched:]
        while quote_at and quote_at[-1] >= matched:
            quote_at.pop()
        for entry in opened:
            if entry == _QUOTE:
                quote_at.append(len(stack))
            stack.append(entry)
        quoted = _QUOTED if quote_at else 0
        continues = interrupting and not opened
        empty_item = -1
        if result == _EMPTY and opened[-1] != _QUOTE:
            empty_item = len(stack) - 1

        if opener is not None:
            fence = opener
            kinds.append(_FENCE | quoted)
            in_paragraph = False
        elif ends is not None:
            kinds.append(_HTML | quoted)
            # Types 1 to 5 may end on their start line.
            if not ends or not any(e in work[q:end].lower() for e in ends):
                html = ends
            in_paragraph = False
        else:
            kinds.append(_TEXT | quoted)
            if result == _SETEXT:
                if not stack:
                    setext.append((para_start, i, level))
                in_paragraph = False
            elif result == _PARAGRAPH:
                if not continues:
                    para_start = i
                in_paragraph = True
            elif result in (_INDENTED, _CONTINUATION):
                # Indented text continues an open paragraph and is code
                # otherwise. A marker that may not interrupt is text.
                in_paragraph = continues
            else:
                in_paragraph = False
    return kinds, setext
