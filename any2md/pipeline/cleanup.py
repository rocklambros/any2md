"""Shared cleanup stages (always last). See spec §4.3."""

from __future__ import annotations

import re
import unicodedata
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from any2md.pipeline import PipelineOptions

Stage = Callable[[str, "PipelineOptions"], str]


def nfc_normalize(text: str, _options: "PipelineOptions") -> str:
    """C1: NFC unicode normalization. Required by SSRM §5.1 for content_hash."""
    return unicodedata.normalize("NFC", text)


def strip_soft_hyphens(text: str, _options: "PipelineOptions") -> str:
    """C2: Remove U+00AD soft hyphen. Frequent PDF artifact."""
    return text.replace("­", "")


# Whitelist of presentation-form ligatures and similar single-glyph compounds
# that are safe to expand. NOT a blanket NFKC pass — that would fold
# superscripts, subscripts, and CJK compatibility characters.
_LIGATURE_TABLE = str.maketrans({
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
    " ": " ",   # non-breaking space → regular space
})


def normalize_ligatures(text: str, _options: "PipelineOptions") -> str:
    """C3: Expand whitelisted ligatures and NBSP only.

    Deliberately not a blanket NFKC pass — see spec §4.3 C3.
    """
    return text.translate(_LIGATURE_TABLE)


_QUOTE_TABLE = str.maketrans({
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
})


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


STAGES: list[Stage] = [
    nfc_normalize,
    strip_soft_hyphens,
    normalize_ligatures,
    normalize_quotes_dashes,
    collapse_whitespace,
]
