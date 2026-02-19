"""Shared utility functions for mdconv."""

import re
import urllib.parse
from pathlib import Path


def sanitize_filename(name: str) -> str:
    """Convert a source filename to a sanitized .md filename.

    Matches existing convention: spaces -> underscores, extension -> .md.
    """
    stem = Path(name).stem
    # Replace spaces with underscores
    stem = stem.replace(" ", "_")
    # Replace characters problematic in filenames
    stem = re.sub(r"[,;:'\"\u2014\u2013]", "", stem)
    # Collapse multiple underscores
    stem = re.sub(r"_+", "_", stem)
    # Strip leading/trailing underscores
    stem = stem.strip("_")
    return stem + ".md"


def extract_title(markdown_text: str, fallback: str) -> str:
    """Extract the first markdown heading as the document title."""
    match = re.search(r"^#{1,3}\s+(.+)", markdown_text, re.MULTILINE)
    if match:
        title = match.group(1).strip()
        # Clean markdown formatting from title
        title = re.sub(r"\*+", "", title)
        title = re.sub(r"_+", " ", title)
        title = title.strip()
        if len(title) > 10:
            return title
    # Fallback: derive from filename
    return fallback.replace("_", " ").strip()


def clean_markdown(text: str) -> str:
    """Clean up markdown for LLM consumption.

    Reduces excessive whitespace while preserving structure.
    """
    # Collapse 3+ consecutive blank lines to 2
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    # Remove trailing whitespace on each line
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    # Ensure file ends with single newline
    text = text.rstrip() + "\n"
    return text


def escape_yaml_string(value: str) -> str:
    """Escape a string for safe inclusion in double-quoted YAML values."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def strip_links(text: str) -> str:
    """Replace markdown links with their display text.

    Converts ``[text](url)`` to ``text``.
    """
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)


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
    # Replace dots and slashes with underscores
    raw = raw.replace(".", "_").replace("/", "_")
    # Strip leading/trailing underscores
    raw = raw.strip("_")
    # Collapse multiple underscores
    raw = re.sub(r"_+", "_", raw)
    return raw + ".md"
