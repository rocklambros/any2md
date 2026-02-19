"""HTML to Markdown converter module."""

from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

import trafilatura
import markdownify
from bs4 import BeautifulSoup

from mdconv.utils import (
    sanitize_filename,
    extract_title,
    clean_markdown,
    strip_links,
    url_to_filename,
    escape_yaml_string,
)


def fetch_url(url: str) -> tuple[str | None, str | None]:
    """Fetch HTML content from a URL.

    Only http and https schemes are accepted.

    Returns (html_string, None) on success or (None, error_message) on failure.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None, f"Unsupported URL scheme: {parsed.scheme!r} (only http/https allowed)"

    try:
        html = trafilatura.fetch_url(url)
        if html is None:
            return None, f"Failed to fetch URL: {url}"
        return html, None
    except Exception as e:
        return None, f"Error fetching URL: {e}"


def _bs4_preclean(html: str) -> str:
    """Remove boilerplate HTML elements before conversion.

    Strips script, style, nav, header, footer, aside, and iframe tags
    along with their contents.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "nav", "header", "footer", "aside", "iframe"]):
        tag.decompose()
    return str(soup)


def convert_html(
    html_path: Path | None,
    output_dir: Path,
    force: bool = False,
    strip_links_flag: bool = False,
    source_url: str | None = None,
    html_content: str | None = None,
) -> bool:
    """Convert HTML to LLM-optimized Markdown.

    When *html_content* is provided it is used directly; otherwise the file
    at *html_path* is read.  When *source_url* is set, frontmatter records
    the URL instead of a local filename.

    Returns True on success, False on failure.
    """
    # Determine output filename
    if source_url:
        out_name = url_to_filename(source_url)
        name_for_error = source_url
    elif html_path is not None:
        out_name = sanitize_filename(html_path.name)
        name_for_error = html_path.name
    else:
        raise ValueError("Either source_url or html_path must be provided")

    out_path = output_dir / out_name

    if out_path.exists() and not force:
        print(f"  SKIP (exists): {out_name}")
        return True

    try:
        # 1. Acquire HTML
        if html_content is not None:
            raw_html = html_content
        elif html_path is not None:
            try:
                raw_html = html_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                raw_html = html_path.read_text(encoding="latin-1")
        else:
            raise ValueError("Either html_content or html_path must be provided")

        # 2. BS4 pre-clean
        cleaned_html = _bs4_preclean(raw_html)

        # 3. trafilatura extract
        md_text = trafilatura.extract(
            cleaned_html,
            include_formatting=True,
            include_links=True,
        )

        # 4. Fallback to markdownify if trafilatura returned nothing
        if not md_text:
            md_text = markdownify.markdownify(
                cleaned_html,
                heading_style="ATX",
                strip=["img"],
            )

        # 5. Clean markdown
        md_text = clean_markdown(md_text)

        # 6. Optionally strip links
        if strip_links_flag:
            md_text = strip_links(md_text)

        # 7. Extract title
        if source_url:
            fallback = urllib.parse.urlparse(source_url).netloc
        elif html_path is not None:
            fallback = html_path.stem
        else:
            fallback = "untitled"
        title = extract_title(md_text, fallback)

        # 8. Word count
        word_count = len(md_text.split())

        # 9. Build frontmatter (escape values for valid YAML)
        if source_url:
            source_field = f'source_url: "{escape_yaml_string(source_url)}"'
        elif html_path is not None:
            source_field = f'source_file: "{escape_yaml_string(html_path.name)}"'
        else:
            source_field = 'source_file: "unknown"'

        frontmatter = (
            f'---\n'
            f'title: "{escape_yaml_string(title)}"\n'
            f'{source_field}\n'
            f'word_count: {word_count}\n'
            f'type: html\n'
            f'---\n\n'
        )

        # 10-11. Write output
        full_text = frontmatter + md_text
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(full_text, encoding="utf-8")
        print(f"  OK: {out_name} ({word_count} words)")
        return True

    except Exception as e:
        print(f"  FAIL: {name_for_error} -- {e}", file=sys.stderr)
        return False
