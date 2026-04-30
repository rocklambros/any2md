"""Shared cleanup stages (always last). See spec §4.3."""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from any2md.pipeline import PipelineOptions

Stage = Callable[[str, "PipelineOptions"], str]


def nfc_normalize(text: str, _options: "PipelineOptions") -> str:
    """C1: NFC unicode normalization. Required by SAGE §5.1 for content_hash."""
    return unicodedata.normalize("NFC", text)


def strip_soft_hyphens(text: str, _options: "PipelineOptions") -> str:
    """C2: Remove U+00AD soft hyphen. Frequent PDF artifact."""
    return text.replace("­", "")


# Whitelist of presentation-form ligatures and similar single-glyph compounds
# that are safe to expand. NOT a blanket NFKC pass — that would fold
# superscripts, subscripts, and CJK compatibility characters.
_LIGATURE_TABLE = str.maketrans(
    {
        "ﬀ": "ff",
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
        "ﬅ": "st",
        "ﬆ": "st",
        " ": " ",  # non-breaking space → regular space
    }
)


def normalize_ligatures(text: str, _options: "PipelineOptions") -> str:
    """C3: Expand whitelisted ligatures and NBSP only.

    Deliberately not a blanket NFKC pass — see spec §4.3 C3.
    """
    return text.translate(_LIGATURE_TABLE)


_QUOTE_TABLE = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
)


def normalize_quotes_dashes(text: str, _options: "PipelineOptions") -> str:
    """C4: Smart quotes → straight; ellipsis → "..."; en/em dashes preserved."""
    text = text.translate(_QUOTE_TABLE)
    text = text.replace("…", "...")
    return text


_INTERWORD_RUNS_RE = re.compile(r"(?<=\S)[ \t]{2,}(?=\S)")
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def collapse_whitespace(text: str, _options: "PipelineOptions") -> str:
    """C5: Collapse inter-word whitespace; trim trailing per line; cap blanks at 2."""
    text = _INTERWORD_RUNS_RE.sub(" ", text)
    text = _TRAILING_WS_RE.sub("", text)
    text = _BLANK_RUN_RE.sub("\n\n", text)
    return text


_FENCE_RE = re.compile(r"^```")


def decode_html_entities(text: str, _options: "PipelineOptions") -> str:
    """C8: Decode HTML entities outside fenced code blocks. Universal.

    Loops ``html.unescape`` until output stabilizes (max 5 iterations) so
    double-encoded entities like ``&amp;amp;`` → ``&amp;`` → ``&`` are
    fully decoded. Some extractors (notably Docling on academic PDFs)
    emit double-encoded entities; a single unescape pass leaves a
    surviving ``&amp;`` in body text.
    """
    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
        else:
            current = line
            for _ in range(5):
                decoded = html.unescape(current)
                if decoded == current:
                    break
                current = decoded
            out.append(current)
    return "\n".join(out)


_INLINE_FN_RE = re.compile(
    r"\[\^(?:\d+|[a-zA-Z][a-zA-Z0-9_-]*)\]"  # [^1] [^note] (markdown footnote refs)
    r"|[¹²³⁰-⁹]"  # superscript digits ¹ ² ³ ⁰-⁹
)
_FOOTNOTES_HEADING_RE = re.compile(
    r"^#{1,3}\s+(footnotes?|notes?|references?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def strip_footnote_markers(text: str, options: "PipelineOptions") -> str:
    """C6: Strip inline footnote markers in body; keep footnotes section.

    Aggressive and maximum profiles only. No-op when no recognizable
    footnotes section exists.
    """
    if options.profile not in ("aggressive", "maximum"):
        return text
    m = _FOOTNOTES_HEADING_RE.search(text)
    if not m:
        return text
    body = text[: m.start()]
    tail = text[m.start() :]
    body = _INLINE_FN_RE.sub("", body)
    return body + tail


_HEADING_RE = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)


def validate(text: str, _options: "PipelineOptions") -> str:
    """C7: Read-only sanity checks. Emits warnings via the pipeline contextvar."""
    from any2md.pipeline import emit_warning

    levels = [len(m.group(1)) for m in _HEADING_RE.finditer(text)]
    h1_count = sum(1 for level in levels if level == 1)
    if h1_count != 1:
        emit_warning(f"validator: H1 count is {h1_count} (expected 1)")
    for prev, curr in zip(levels, levels[1:]):
        if curr > prev + 1:
            emit_warning(f"validator: heading level skip h{prev} -> h{curr}")
            break
    return text


STAGES: list[Stage] = [
    nfc_normalize,
    strip_soft_hyphens,
    normalize_ligatures,
    normalize_quotes_dashes,
    collapse_whitespace,
    decode_html_entities,
    strip_footnote_markers,
    validate,
]
