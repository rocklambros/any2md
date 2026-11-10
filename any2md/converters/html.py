"""HTML to Markdown converter (v1.0)."""

from __future__ import annotations

import re
import sys
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path

import markdownify
import trafilatura
from bs4 import BeautifulSoup

from any2md import _logging, pipeline
from any2md._http import safe_fetch
from any2md.converters import add_warnings, is_quiet
from any2md.frontmatter import SourceMeta, compose
from any2md.pipeline import PipelineOptions
from any2md.utils import (
    atomic_write_text,
    read_text_with_fallback,
    sanitize_filename,
    scrub_url_credentials,
    url_to_filename,
)


_MAX_FILE_SIZE = 100 * 1024 * 1024


def fetch_url(url: str) -> tuple[str | None, str | None]:
    """Fetch HTML from a URL using the SSRF-safe fetcher.

    Returns (html_string, None) on success or (None, error_message)
    on failure. Per-hop host revalidation defends against DNS rebind
    via redirects.
    """
    body, _headers, err = safe_fetch(url)
    if err:
        return None, err
    if body is None:
        return None, f"empty body for {url}"
    return body.decode("utf-8", errors="replace"), None


def _http_last_modified(url: str) -> str | None:
    """Single HEAD request for Last-Modified. Best-effort.

    SSRF-safe: same scheme + IP validation as ``fetch_url``.
    """
    _body, headers, err = safe_fetch(url, method="HEAD")
    if err or not headers:
        return None
    lm = headers.get("Last-Modified")
    if not lm:
        return None
    try:
        return parsedate_to_datetime(lm).date().isoformat()
    except (TypeError, ValueError):
        return None


def _bs4_preclean(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(
        ["script", "style", "nav", "header", "footer", "aside", "iframe"]
    ):
        tag.decompose()
    return str(soup)


def _extract(raw_html: str) -> tuple[str, str]:
    """Returns (markdown, extracted_via)."""
    md = trafilatura.extract(
        raw_html,
        output_format="markdown",
        include_formatting=True,
        include_links=True,
    )
    if md:
        return md, "trafilatura"
    cleaned = _bs4_preclean(raw_html)
    # Many pages build tables without <thead>; infer the first row as the
    # header so markdownify does not emit an empty header row.
    md = markdownify.markdownify(
        cleaned, heading_style="ATX", strip=["img"], table_infer_header=True
    )
    return md, "trafilatura+bs4_fallback"


_WS_RE = re.compile(r"\s+")
_ATX_H1_RE = re.compile(r"^#[ \t]+\S")
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
_WRAPPING_EMPHASIS_RE = re.compile(r"^(\*\*|__|\*|_)(.+?)\1$")


def _one_line(text: str) -> str:
    """Collapse every whitespace run (newlines included) to one space."""
    return _WS_RE.sub(" ", text).strip()


def _visible_h1(raw_html: str) -> str | None:
    """Return the page's own ``<h1>`` text when the page has exactly one.

    Empty ``<h1>`` wrappers (logo images, icon fonts) are ignored. Two or
    more non-empty ``<h1>`` elements make the document title ambiguous,
    so the caller falls back to the metadata title instead of guessing.
    """
    soup = BeautifulSoup(raw_html, "lxml")
    texts = [t for t in (_one_line(h.get_text()) for h in soup.find_all("h1")) if t]
    return texts[0] if len(texts) == 1 else None


def _unwrap_emphasis(text: str) -> str:
    """Strip emphasis markers that wrap the whole line (``**x**``, ``***x***``)."""
    for _ in range(3):  # bold-italic nests at most three marker levels deep
        m = _WRAPPING_EMPHASIS_RE.match(text)
        if not m:
            break
        text = _one_line(m.group(2))
    return text


def _ensure_h1(body: str, title: str | None) -> str:
    """Guarantee the body opens with one H1 when a title is known.

    trafilatura keeps a heading only when it sits inside the content node
    it selects, so a page ``<h1>`` in a hero banner or ``<header>`` block
    never reaches the body. This puts it back so the C7 validator and the
    README's single-H1 guarantee hold for HTML/URL output.

    - Body already has an ATX H1 outside fenced code: returned unchanged.
    - No usable title: returned unchanged (the validator still warns).
    - First non-blank line repeats the title, as plain or emphasized text
      (case-insensitive): that line is promoted to the H1 so the title
      does not appear twice.
    - Otherwise ``# <title>`` and a blank line are prepended.
    """
    lines = body.split("\n")
    in_fence = False
    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        elif not in_fence and _ATX_H1_RE.match(line):
            return body

    heading = _one_line(title or "")
    if not heading:
        return body

    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is None:
        return f"# {heading}\n"

    candidate = _unwrap_emphasis(_one_line(lines[first]))
    if candidate.casefold() == heading.casefold():
        # Keep the page's own wording and casing for the promoted line.
        lines[first] = f"# {candidate}"
        return "\n".join(lines)

    return f"# {heading}\n\n" + "\n".join(lines[first:])


_ATX_HEADING_RE = re.compile(r"^(#{1,6})(?=[ \t]+\S)")


def _normalize_heading_levels(body: str) -> str:
    """Re-rank body headings so levels never skip below the H1.

    CMS templates often mark sections as H3/H4 directly under the page
    H1, which the C7 validator reports as an ``h1 -> h3`` skip. Each
    heading's new level is its depth in a stack of the original levels
    of the sections still open above it, so siblings stay siblings and
    nesting is kept: ``H3, H3, H4, H3`` becomes ``H2, H2, H3, H2``.

    Structured-lane S4 (``enforce_heading_hierarchy``) flattens one
    heading at a time, which turns sibling H3s into H2 + H3 children;
    that is why this lane uses its own ranking. H1 lines are never
    moved and nothing is ever promoted to H1. Only the ``#`` prefix of
    a heading line changes. A body with no skips is returned unchanged.
    """
    lines = body.split("\n")
    stack: list[int] = [1]  # original levels of open sections; H1 at bottom
    in_fence = False
    changed = False
    for i, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        m = None if in_fence else _ATX_HEADING_RE.match(line)
        if not m:
            continue
        level = len(m.group(1))
        if level == 1:
            stack = [1]
            continue
        while len(stack) > 1 and stack[-1] >= level:
            stack.pop()
        stack.append(level)
        new_level = len(stack)
        if new_level != level:
            lines[i] = "#" * new_level + line[level:]
            changed = True
    return "\n".join(lines) if changed else body


def _extract_metadata(
    raw_html: str,
) -> tuple[str | None, list[str], str | None, str | None, list[str]]:
    """Returns (title_hint, authors, organization, date, keywords)."""
    try:
        bare = trafilatura.bare_extraction(
            raw_html, with_metadata=True, output_format="python"
        )
    except Exception:  # noqa: BLE001
        return None, [], None, None, []
    if not bare:
        return None, [], None, None, []
    # trafilatura >=2.0 returns a Document object; older versions return dict.
    if hasattr(bare, "as_dict"):
        data = bare.as_dict()
    elif isinstance(bare, dict):
        data = bare
    else:
        data = {
            k: getattr(bare, k, None)
            for k in ("title", "author", "sitename", "date", "categories")
        }
    title = data.get("title")
    authors_raw = data.get("author") or ""
    authors = [a.strip() for a in authors_raw.split(",") if a.strip()]
    org = data.get("sitename")
    d = data.get("date")
    kw = data.get("categories") or []
    if isinstance(kw, str):
        kw = [k.strip() for k in kw.split(",") if k.strip()]
    return title, authors, org, d, list(kw)


def convert_html(
    html_path: Path | None,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
    strip_links_flag: bool = False,
    source_url: str | None = None,
    html_content: str | None = None,
) -> bool:
    if options is None:
        options = PipelineOptions(strip_links=strip_links_flag)

    if source_url:
        out_name = url_to_filename(source_url)
        name_for_error = source_url
    elif html_path is not None:
        out_name = sanitize_filename(html_path.name)
        name_for_error = html_path.name
    else:
        print(
            "  FAIL: source_url or html_path required", file=sys.stderr
        )  # log-safe: literal
        return False

    out_path = output_dir / out_name
    if out_path.exists() and not force:
        print(f"  SKIP (exists): {_logging.safe_oneline(out_name)}")
        return True

    try:
        if html_content is not None:
            raw_html = html_content
        elif html_path is not None:
            file_size = html_path.stat().st_size
            if file_size > _MAX_FILE_SIZE:
                _logging.fail(
                    f"{name_for_error} -- file too large "
                    f"({file_size} bytes, max {_MAX_FILE_SIZE})"
                )
                return False
            raw_html = read_text_with_fallback(html_path)
        else:
            print(
                "  FAIL: html_content or html_path required", file=sys.stderr
            )  # log-safe: literal
            return False

        md_text, extracted_via = _extract(raw_html)
        title_hint, authors, org, doc_date, keywords = _extract_metadata(raw_html)
        # Runs before pipeline.run so every text-lane stage, the C7
        # validator, and compose() (content_hash, token_estimate, chunk
        # level, abstract) all see the final body with its H1. The
        # visible <h1> wins over the metadata title because it is the
        # heading a reader sees; compose() keeps the metadata title as
        # seo_title when the two differ.
        md_text = _ensure_h1(md_text, _visible_h1(raw_html) or title_hint)
        md_text = _normalize_heading_levels(md_text)

        if source_url and not doc_date:
            doc_date = _http_last_modified(source_url)
        if not doc_date:
            doc_date = date.today().isoformat()

        md_text, warnings = pipeline.run(md_text, "text", options)
        add_warnings(warnings)

        meta = SourceMeta(
            title_hint=title_hint,
            authors=authors,
            organization=org,
            date=doc_date,
            keywords=keywords,
            pages=None,
            word_count=len(md_text.split()),
            source_file=html_path.name if html_path else None,
            source_url=source_url,
            doc_type="html",
            extracted_via=extracted_via,
            lane="text",
            seo_title=title_hint,
        )
        full = compose(md_text, meta, options, overrides=options.frontmatter_overrides)

        output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out_path, full)
        wc = meta.word_count or 0
        suffix = f", {len(warnings)} warning(s)" if warnings else ""
        if not is_quiet():
            print(f"  OK: {_logging.safe_oneline(out_name)} ({wc} words{suffix})")
        return True

    except (OSError, ValueError, TypeError) as e:
        _logging.fail(f"{name_for_error} -- {e}")
        return False


def convert_url(
    url: str,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
    strip_links_flag: bool = False,
) -> bool:
    """Convenience wrapper: fetch a URL and convert to Markdown."""
    scrubbed_url, warnings = scrub_url_credentials(url)
    for w in warnings:
        if w == "credentials":
            _logging.warn("stripped credentials from URL")
        else:
            _logging.warn(f"stripped sensitive query parameter '{w}' from URL")
    url = scrubbed_url
    html_content, err = fetch_url(url)
    if err:
        _logging.fail(f"{url} -- {err}")
        return False
    return convert_html(
        None,
        output_dir,
        options=options,
        force=force,
        strip_links_flag=strip_links_flag,
        source_url=url,
        html_content=html_content,
    )
