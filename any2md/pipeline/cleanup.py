"""Shared cleanup stages (always last). See spec §4.3."""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Callable, TYPE_CHECKING

from any2md.pipeline.blocks import fence_runs, fenced_lines

if TYPE_CHECKING:
    from any2md.pipeline import PipelineOptions

Stage = Callable[[str, "PipelineOptions"], str]


def _map_outside_fences(text: str, fn: Callable[[str], str]) -> str:
    """Apply a per-line rewrite to every line outside fenced code."""
    lines = text.split("\n")
    return "\n".join(
        line if code else fn(line) for line, code in zip(lines, fenced_lines(text))
    )


def nfc_normalize(text: str, _options: "PipelineOptions") -> str:
    """C1: NFC unicode normalization. Required by SAGE §5.1 for content_hash.

    Applies inside fenced code too. ``content_hash`` is defined over the
    NFC form of the whole body, and NFC only swaps canonically equivalent
    sequences, so code reads the same afterward.
    """
    return unicodedata.normalize("NFC", text)


def strip_soft_hyphens(text: str, _options: "PipelineOptions") -> str:
    """C2: Remove U+00AD soft hyphen. Frequent PDF artifact.

    Applies inside fenced code too. The character is invisible, no
    language gives it meaning, and in code it breaks the token it sits in.
    """
    return text.replace("\u00ad", "")  # escaped: invisible as a literal


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

    Applies inside fenced code too. A presentation-form ligature in an
    identifier ("de\ufb01ne") and an NBSP in indentation are extraction or
    word-processor artifacts that make the code invalid. Code that needs
    those characters writes them as escapes.
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
    """C4: Smart quotes → straight, ellipsis → "...", en/em dashes preserved.

    Fenced code is left alone. Curly quotes and an ellipsis there are
    often string content, and straightening them changes what the
    program prints.
    """
    return _map_outside_fences(
        text, lambda line: line.translate(_QUOTE_TABLE).replace("…", "...")
    )


_INTERWORD_RUNS_RE = re.compile(r"(?<=\S)[ \t]{2,}(?=\S)")


def collapse_whitespace(text: str, _options: "PipelineOptions") -> str:
    """C5: Collapse inter-word whitespace, trim trailing space, cap blank runs.

    Fenced code is left alone: alignment, trailing spaces, and blank
    runs can be significant there.
    """
    lines = text.split("\n")
    n = len(lines)
    out: list[str] = []
    for code, start, end in fence_runs(fenced_lines(text)):
        if code:
            out.extend(lines[start:end])
        else:
            out.extend(_collapse_prose(lines[start:end], start == 0, end == n))
    return "\n".join(out)


def _collapse_prose(lines: list[str], open_start: bool, open_end: bool) -> list[str]:
    """Collapse one run of prose lines.

    ``open_start`` and ``open_end`` say whether the run touches the start
    or end of the text rather than a fence line. The cap matches
    ``\\n{3,}`` -> ``\\n\\n`` over the whole text. A run of empty lines
    between two non-empty lines spans one more newline than it has
    lines, so it keeps one empty line. Each open edge removes one of
    those newlines, so the run keeps one more empty line per open edge.
    A fence line counts as non-empty.
    """
    text = _INTERWORD_RUNS_RE.sub(" ", "\n".join(lines))
    # Per-line rstrip, not ``[ \\t]+$``: the regex rescans a long run of
    # spaces from every start position when the run does not end the line,
    # which is quadratic (CWE-1333).
    out: list[str] = []
    blank = 0
    at_start = True
    for row in text.split("\n"):
        row = row.rstrip(" \t")
        if not row:
            blank += 1
            continue
        if blank:
            out.extend([""] * min(blank, 2 if at_start and open_start else 1))
            blank = 0
        at_start = False
        out.append(row)
    if blank:
        edges = (at_start and open_start) + open_end
        out.extend([""] * min(blank, 1 + edges))
    return out


def decode_html_entities(text: str, _options: "PipelineOptions") -> str:
    """C8: Decode HTML entities outside fenced code blocks. Universal.

    Loops ``html.unescape`` until output stabilizes (max 5 iterations) so
    double-encoded entities like ``&amp;amp;`` → ``&amp;`` → ``&`` are
    fully decoded. Some extractors (notably Docling on academic PDFs)
    emit double-encoded entities; a single unescape pass leaves a
    surviving ``&amp;`` in body text.
    """

    def _decode(line: str) -> str:
        for _ in range(5):
            decoded = html.unescape(line)
            if decoded == line:
                break
            line = decoded
        return line

    return _map_outside_fences(text, _decode)


# Inline link: [text](url) or [text](url "title"). The URL may contain one
# level of balanced parentheses (Wikipedia-style ``Python_(language)``).
# The ``(?<!!)`` right before "[" keeps images (``![alt](src)``) intact.
# It sits after the backslash run so ``!\\[t](u)``, a link after a literal
# "!", is still stripped.
#
# Bounded and unambiguous so hostile lines stay linear (CWE-1333): a link
# opens only at an unescaped "[" (the backslash run before it, kept in
# group 1, has even length) and its text stops at the next unescaped
# bracket (a run of "[" no longer rescans to the next "]" from every
# start), escaped brackets such as ``\[`` stay in the text, the URL and
# title have length caps, and the URL's two alternatives never start with
# the same character.
_INLINE_LINK_RE = re.compile(
    r"(?<!\\)((?:\\\\)*)(?<!!)\[((?:[^\[\]\\]|\\[\s\S])*)\]"
    r"\((?:[^()\s]|\([^()\s]{0,256}\)){0,2048}"
    r"(?:[ \t]+\"[^\"\n]{0,512}\")?\)"
)
_INLINE_CODE_SPLIT_RE = re.compile(r"(`[^`]*`)")


def strip_links(text: str, options: "PipelineOptions") -> str:
    """C9: Replace inline links with their text when ``strip_links`` is set.

    Driven by ``--strip-links`` and implied by ``--profile maximum``.
    Images, fenced code blocks, and inline code spans are left untouched.
    """
    if not options.strip_links:
        return text

    def _strip(line: str) -> str:
        if "](" not in line:
            return line
        # Odd-indexed parts are inline code spans; leave them as written.
        parts = _INLINE_CODE_SPLIT_RE.split(line)
        for i in range(0, len(parts), 2):
            parts[i] = _INLINE_LINK_RE.sub(r"\1\2", parts[i])
        return "".join(parts)

    return _map_outside_fences(text, _strip)


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
    lines = text.split("\n")
    fenced = fenced_lines(text)
    # A "## Notes" line inside a code sample is not the footnotes section.
    heading = next(
        (
            k
            for k, line in enumerate(lines)
            if not fenced[k] and _FOOTNOTES_HEADING_RE.match(line)
        ),
        None,
    )
    if heading is None:
        return text
    body = [
        line if fenced[k] else _INLINE_FN_RE.sub("", line)
        for k, line in enumerate(lines[:heading])
    ]
    return "\n".join(body + lines[heading:])


_HEADING_RE = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)


def validate(text: str, _options: "PipelineOptions") -> str:
    """C7: Read-only sanity checks. Emits warnings via the pipeline contextvar."""
    from any2md.pipeline import emit_warning

    # A "#" line inside fenced code is a comment, not a heading.
    lines = text.split("\n")
    levels = [
        len(m.group(1))
        for line, code in zip(lines, fenced_lines(text))
        if not code and (m := _HEADING_RE.match(line))
    ]
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
    strip_links,  # after entity decoding so &#91;-encoded brackets are seen
    strip_footnote_markers,
    validate,
]
