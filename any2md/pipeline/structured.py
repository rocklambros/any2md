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


def enforce_heading_hierarchy(text: str, _options: "PipelineOptions") -> str:
    """S4: Ensure single H1 and no skipped levels.

    - If no H1 exists, the first heading is promoted to H1.
    - Subsequent H1s are demoted to H2.
    - Skipped levels are flattened: a heading that's > prev_level + 1
      becomes prev_level + 1.
    """
    matches = list(_HEADING_LINE_RE.finditer(text))
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

    # Flatten skipped levels
    for i in range(1, len(levels)):
        if levels[i] > levels[i - 1] + 1:
            levels[i] = levels[i - 1] + 1

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
