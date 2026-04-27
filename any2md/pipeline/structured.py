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

_IMG_LINK_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_HTML_FIGURE_RE = re.compile(
    r"<figure[^>]*>(?:.*?)<figcaption[^>]*>(.*?)</figcaption>(?:.*?)</figure>",
    re.DOTALL | re.IGNORECASE,
)
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
            return f"{caption_line}\n\n![{alt}]({url})" if caption_line else f"![{alt}]({url})"
        return caption_line

    text = _IMG_LINK_RE.sub(_img_repl, text)

    def _figure_repl(match: re.Match[str]) -> str:
        cap = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        return f"*Figure: {cap}*" if cap else ""

    text = _HTML_FIGURE_RE.sub(_figure_repl, text)

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


_HEADING_LINE_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)


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
        out.append(text[last:m.start()])
        out.append("#" * new_level + " " + m.group(2))
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

STAGES.extend([
    strip_repeated_byline,
    dedupe_toc_table,
    strip_cover_artifacts,
    strip_orphan_punctuation,
])
