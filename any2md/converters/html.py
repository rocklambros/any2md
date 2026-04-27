"""HTML to Markdown converter (v1.0)."""

from __future__ import annotations

import ipaddress
import socket
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import markdownify
import trafilatura
from bs4 import BeautifulSoup

from any2md import pipeline
from any2md.converters import add_warnings, is_quiet
from any2md.frontmatter import SourceMeta, compose
from any2md.pipeline import PipelineOptions
from any2md.utils import (
    read_text_with_fallback,
    sanitize_filename,
    url_to_filename,
)

_MAX_FILE_SIZE = 100 * 1024 * 1024


def _validate_url_host(url: str) -> str | None:
    """Validate that a URL does not point to a private/reserved IP.

    Returns an error message if the host is disallowed, or None if safe.
    """
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return f"No hostname in URL: {url}"
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return f"Cannot resolve hostname: {hostname}"
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            addr.is_private
            or addr.is_reserved
            or addr.is_loopback
            or addr.is_link_local
        ):
            return f"URL resolves to disallowed address: {ip_str}"
    return None


def fetch_url(url: str) -> tuple[str | None, str | None]:
    """Fetch HTML content from a URL.

    Only http and https schemes are accepted. SSRF protection blocks
    requests to private/reserved/loopback addresses.

    Returns (html_string, None) on success or (None, error_message) on failure.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None, f"Unsupported URL scheme: {parsed.scheme!r}"
    err = _validate_url_host(url)
    if err:
        return None, err
    try:
        html = trafilatura.fetch_url(url)
        if html is None:
            return None, f"Failed to fetch URL: {url}"
        return html, None
    except Exception as e:  # noqa: BLE001
        return None, f"Error fetching URL: {e}"


def _http_last_modified(url: str) -> str | None:
    """Single HEAD request for Last-Modified. Best-effort."""
    try:
        req = urllib.request.Request(
            url,
            method="HEAD",
            headers={"User-Agent": "any2md/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            lm = resp.headers.get("Last-Modified")
            if lm:
                from email.utils import parsedate_to_datetime

                return parsedate_to_datetime(lm).date().isoformat()
    except Exception:  # noqa: BLE001
        pass
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
    md = markdownify.markdownify(cleaned, heading_style="ATX", strip=["img"])
    return md, "trafilatura+bs4_fallback"


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
        print("  FAIL: source_url or html_path required", file=sys.stderr)
        return False

    out_path = output_dir / out_name
    if out_path.exists() and not force:
        print(f"  SKIP (exists): {out_name}")
        return True

    try:
        if html_content is not None:
            raw_html = html_content
        elif html_path is not None:
            file_size = html_path.stat().st_size
            if file_size > _MAX_FILE_SIZE:
                print(
                    f"  FAIL: {name_for_error} -- file too large "
                    f"({file_size} bytes, max {_MAX_FILE_SIZE})",
                    file=sys.stderr,
                )
                return False
            raw_html = read_text_with_fallback(html_path)
        else:
            print("  FAIL: html_content or html_path required", file=sys.stderr)
            return False

        md_text, extracted_via = _extract(raw_html)
        title_hint, authors, org, doc_date, keywords = _extract_metadata(raw_html)

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
        )
        full = compose(md_text, meta, options, overrides=options.frontmatter_overrides)

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(full, encoding="utf-8", newline="\n")
        wc = meta.word_count or 0
        suffix = f", {len(warnings)} warning(s)" if warnings else ""
        if not is_quiet():
            print(f"  OK: {out_name} ({wc} words{suffix})")
        return True

    except (OSError, ValueError, TypeError) as e:
        print(f"  FAIL: {name_for_error} -- {e}", file=sys.stderr)
        return False


def convert_url(
    url: str,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
    strip_links_flag: bool = False,
) -> bool:
    """Convenience wrapper: fetch a URL and convert to Markdown."""
    html_content, err = fetch_url(url)
    if err:
        print(f"  FAIL: {url} -- {err}", file=sys.stderr)
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
