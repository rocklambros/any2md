"""Shared utility functions for any2md.

Slimmed in v1.0: frontmatter and markdown cleanup moved to dedicated
modules (any2md/frontmatter.py, any2md/pipeline/cleanup.py).
"""

from __future__ import annotations

import re
import urllib.parse
from pathlib import Path

_CTRL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_SPECIAL_CHARS_RE = re.compile(r"[,;:'\"—–]")
_COLLAPSE_UNDERSCORES_RE = re.compile(r"_+")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def sanitize_filename(name: str) -> str:
    """Convert a source filename to a sanitized .md filename.

    Strips control characters, null bytes, and path separators.
    Matches existing convention: spaces -> underscores, extension -> .md.
    """
    stem = Path(name).stem
    stem = _CTRL_CHARS_RE.sub("", stem)
    stem = stem.replace("/", "").replace("\\", "")
    stem = stem.replace(" ", "_")
    stem = _SPECIAL_CHARS_RE.sub("", stem)
    stem = _COLLAPSE_UNDERSCORES_RE.sub("_", stem)
    stem = stem.strip("_")
    if not stem:
        stem = "untitled"
    return stem + ".md"


def strip_links(text: str) -> str:
    """Replace markdown links with their display text.

    Converts ``[text](url)`` to ``text``. Used by --strip-links CLI flag
    (removed in Phase 4 once gating moves to the pipeline).
    """
    return _LINK_RE.sub(r"\1", text)


def read_text_with_fallback(path: Path) -> str:
    """Read a text file, trying utf-8 first then falling back to latin-1."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def safe_dir_name(name: str) -> str:
    """Conservative directory-name sanitizer: alphanumeric/_/- only.

    Used for output sub-directories whose name comes from an untrusted
    input filename stem. Replaces every non-allowed char with ``_``,
    collapses runs of ``_``, strips leading/trailing ``_``, and falls
    back to ``"untitled"`` for empty results.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", name)
    cleaned = _COLLAPSE_UNDERSCORES_RE.sub("_", cleaned)
    cleaned = cleaned.strip("_") or "untitled"
    return cleaned


def url_to_filename(url: str) -> str:
    """Convert a URL to a sanitized .md filename.

    Uses the netloc and path components, replacing dots and slashes
    with underscores and collapsing duplicates.

    Example::

        >>> url_to_filename("https://example.com/blog/my-post")
        'example_com_blog_my-post.md'
    """
    parsed = urllib.parse.urlparse(url)
    raw = parsed.netloc + parsed.path
    raw = raw.replace(".", "_").replace("/", "_")
    raw = raw.strip("_")
    raw = _COLLAPSE_UNDERSCORES_RE.sub("_", raw)
    return raw + ".md"
