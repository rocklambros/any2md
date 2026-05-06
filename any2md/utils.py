"""Shared utility functions for any2md.

Slimmed in v1.0: frontmatter and markdown cleanup moved to dedicated
modules (any2md/frontmatter.py, any2md/pipeline/cleanup.py).
"""

from __future__ import annotations

import os
import re
import tempfile
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


def atomic_write_text(out_path: Path, content: str) -> None:
    """Write text atomically; refuse to clobber a symlink target.

    Creates a sibling temp file in ``out_path``'s parent dir, fsyncs,
    then ``os.replace``s it over ``out_path``. If ``out_path`` is a
    pre-existing symlink, raises ``ValueError`` rather than overwriting
    whatever the link points to. Defends against symlink-redirect
    attacks at the output path and partial-write windows for concurrent
    readers.
    """
    if out_path.is_symlink():
        raise ValueError(f"refusing to write through symlink: {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(
        prefix=".any2md-", suffix=".tmp", dir=out_path.parent
    )
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, out_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


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

    Uses the hostname and path components (userinfo and port excluded),
    replacing dots and slashes with underscores and collapsing duplicates.

    Example::

        >>> url_to_filename("https://example.com/blog/my-post")
        'example_com_blog_my-post.md'
    """
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    raw = host + parsed.path
    raw = raw.replace(".", "_").replace("/", "_")
    raw = raw.strip("_")
    raw = _COLLAPSE_UNDERSCORES_RE.sub("_", raw)
    return raw + ".md"


_SECRET_PARAM_RE = re.compile(
    r"^(token|api[_-]?key|access[_-]?token|bearer|signature|sig|password|secret|aws[_-]?session[_-]?token)$",
    re.IGNORECASE,
)


def scrub_url_credentials(url: str) -> tuple[str, list[str]]:
    """Strip userinfo and sensitive query params from a URL.

    Returns ``(scrubbed_url, warnings)``. Each warning names the kind
    that was stripped — ``"credentials"`` for userinfo, or the
    parameter key for sensitive query params. Values are NEVER echoed.

    IPv6 hosts have brackets reconstructed (``urlsplit().hostname``
    returns the bracketless form).
    """
    parsed = urllib.parse.urlsplit(url)
    warnings: list[str] = []

    if parsed.username or parsed.password:
        warnings.append("credentials")
        host = parsed.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        netloc = host + (f":{parsed.port}" if parsed.port else "")
        parsed = parsed._replace(netloc=netloc)

    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    kept = []
    for k, v in pairs:
        if _SECRET_PARAM_RE.match(k):
            warnings.append(k)
        else:
            kept.append((k, v))
    parsed = parsed._replace(query=urllib.parse.urlencode(kept))

    return urllib.parse.urlunsplit(parsed), warnings
