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
