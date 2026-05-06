"""any2md/heuristics.py

Field-derivation refinements that go beyond what raw extractors give us.
Every function is pure (input → output, no side effects) except
arxiv_lookup which makes one network call and emits a warning on failure.

Called from frontmatter.compose() and converter modules to refine
candidate values before YAML emission.
"""

from __future__ import annotations

import html
import re
from typing import NamedTuple

from any2md import _logging
from any2md.pipeline import Profile  # type alias


# --------------------------------------------------------------------- #
# Internal regexes & constants (spec §4.2)
# --------------------------------------------------------------------- #

# PDF Creator strings that mean "software", not "organization"
_SOFTWARE_CREATORS_RE = re.compile(
    r"^(LaTeX|.*acmart|.*pdfTeX|.*XeTeX|.*LuaTeX|"
    r"Adobe (InDesign|Acrobat|Illustrator|PageMaker|FrameMaker|Distiller)|"
    r"Microsoft.{0,20}Word|Microsoft.{0,20}Office|Microsoft.{0,20}PowerPoint|"
    r"Apple Pages|LibreOffice|OpenOffice|Calligra|"
    r"Pandoc|Typst|Quarto|Sphinx|MkDocs|"
    r"PyMuPDF|HTML Tidy|wkhtmltopdf|Chromium|Headless Chrome|"
    r"Word for|Mac OS X|Skia/PDF|Outlook|"
    r"Google Docs|Notion|Obsidian)",
    re.IGNORECASE,
)

# Cover-page H1 values to skip (case-insensitive after stripping)
_COVER_PAGE_H1_VALUES = frozenset(
    {
        "international standard",
        "technical report",
        "technical specification",
        "publicly available specification",
        "draft international standard",
        "final draft international standard",
        "white paper",
        "whitepaper",
        "research note",
        "request for comments",
    }
)

# H1 / H2 line detectors (markdown ATX style)
_H1_LINE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_H2_LINE_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
# Markdown emphasis chars stripped when probing an H2 for non-empty content
# (mirrors derive_title's emphasis-stripping so headings like ``## ***``
# are treated as empty rather than yielding a useless title).
_MD_EMPHASIS_STRIP_RE = re.compile(r"[*_]+")

# DOCX line-break course-code / document-type prefix detector. Matches
# strings like "COMP 4441 Final Project " (course code followed by
# document-type marker). The trailing space is required so we only
# split when there's content after the marker.
_DOCX_PREFIX_RE = re.compile(
    r"^(?:[A-Z]{2,5}\s*\d{2,5}\s+)?"
    r"(?:Final Project|Final Paper|Term Paper|Thesis|Dissertation|"
    r"Research Paper|Capstone Project)\s+",
)

# Patterns marking a paragraph as byline / cover blurb / TOC
_BYLINE_DETECT_RE = re.compile(
    r"^[A-Z][A-Z .,\-&'/]{8,}\d.*,",
)
_COVER_BLURB_KEYWORDS = (
    "feedback",
    "qr code",
    "scan the",
    "customer feedback form",
    "third edition",
    "corrected version",
    # License notices (common on standards docs and licensed content)
    "licensed to",
    "single user licence",
    "single user license",
    "iso store order",
    "all rights reserved",
    "copying and networking prohibited",
)
_TOC_LINE_HINTS_RE = re.compile(r"\.{3,}\s*\d+|^\s*page\s+\d+", re.IGNORECASE)

# Markdown inline link: [text](url) → text
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")

# Abstract / Summary heading detection (H2 or H3, case-insensitive)
_ABSTRACT_HEADING_RE = re.compile(
    r"^#{2,3}\s+(?:Abstract|ABSTRACT|Summary|SUMMARY)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Sentence terminator for truncation (period/question/exclamation followed
# by whitespace or end-of-string)
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")

# Author byline cleaning (digits are affiliation markers, drop them)
_AFFIL_DIGITS_RE = re.compile(r"\s+\d+(?:\s*,\s*\d+)*\b")

# "Authors:" / "Author:" / "By" prefixes
_AUTHORS_PREFIX_RE = re.compile(
    r"^(?:Authors?\s*:|By)\s+(.+?)$",
    re.IGNORECASE | re.MULTILINE,
)

# Academic byline detection — line of caps-or-titlecase names, typically
# with digit affiliation markers, comma-separated. We use this only at
# aggressive profile.
_ACADEMIC_BYLINE_RE = re.compile(
    r"^[A-Z][A-Z .'\-]{2,}(?:\s+\d+(?:\s*,\s*\d+)*)?"
    r"(?:\s*,\s*[A-Z][A-Z .'\-]{2,}(?:\s+\d+(?:\s*,\s*\d+)*)?)+\s*$",
)

# arxiv ID pattern in filename
_ARXIV_FILENAME_RE = re.compile(
    r"(?<!\d)(\d{4}\.\d{4,5})(?:v\d+)?(?=\.pdf$|\.|$)",
    re.IGNORECASE,
)


class OrgFilterResult(NamedTuple):
    organization: str | None
    produced_by: str | None


def filter_organization(creator_value: str | None) -> OrgFilterResult:
    """Distinguish real organization names from PDF Creator software junk.

    - When `creator_value` matches a known software pattern, returns
      OrgFilterResult(None, creator_value).
    - Otherwise returns OrgFilterResult(creator_value, None).
    - Empty/None input returns OrgFilterResult(None, None).
    """
    if creator_value is None:
        return OrgFilterResult(None, None)
    stripped = creator_value.strip()
    if not stripped:
        return OrgFilterResult(None, None)
    if _SOFTWARE_CREATORS_RE.match(stripped):
        return OrgFilterResult(None, creator_value)
    return OrgFilterResult(creator_value, None)


def refine_title(
    candidate: str,
    body: str,
    *,
    source_url: str | None = None,
    profile: Profile = "aggressive",
) -> str:
    """Replace candidate when it looks like cover-page boilerplate.

    Behaviors:
      - If candidate (case-insensitive, stripped) matches a known
        cover-page-boilerplate H1 ("INTERNATIONAL STANDARD",
        "TECHNICAL REPORT", "WHITE PAPER", etc.), prefer the first H2
        in the body as the title.
      - For source_url ending in *.wikipedia.org, strip a leading
        "Wikipedia:" or "WP:" namespace prefix.
      - DOCX line-broken H1 (aggressive only): when candidate contains
        an explicit delimiter (" - ", colon-and-space at < 30% mark)
        AND the segment before the delimiter looks like a course code or
        document type prefix (e.g., "COMP 4441 Final Project"), drop the
        prefix.

    Conservative profile: only the cover-page-boilerplate skip and the
    Wikipedia namespace strip. DOCX line-break refinement stays off.
    """
    if not candidate:
        return candidate

    refined = candidate.strip()

    # Cover-page boilerplate skip (both profiles). Walk H2 lines and
    # pick the first one whose content is non-empty after stripping
    # markdown emphasis. The original single-match logic returned ""
    # when the first H2 was emphasis-only (``## ***``) or contained
    # only whitespace-equivalent unicode; iterating line-by-line also
    # prevents the regex's ``\s+`` from grabbing the next paragraph's
    # first word as fake H2 content.
    if refined.lower() in _COVER_PAGE_H1_VALUES:
        for line in body.splitlines():
            if not line.startswith("## "):
                continue
            candidate_h2 = line[3:].strip()
            probe = _MD_EMPHASIS_STRIP_RE.sub("", candidate_h2).strip()
            if probe:
                return candidate_h2

    # Wikipedia namespace prefix strip (aggressive only). Only apply
    # when stripping leaves a non-empty remainder; otherwise keep the
    # candidate as-is rather than emit "".
    if profile != "conservative" and source_url:
        try:
            from urllib.parse import urlparse

            host = (urlparse(source_url).hostname or "").lower()
        except Exception:  # noqa: BLE001
            host = ""
        if host == "wikipedia.org" or host.endswith(".wikipedia.org"):
            for prefix in ("Wikipedia:", "WP:"):
                if refined.startswith(prefix):
                    stripped = refined[len(prefix) :].strip()
                    if stripped:
                        refined = stripped
                    break

    # DOCX line-break course-code / document-type prefix split
    # (aggressive only). Best-effort: only fires when an explicit
    # "Final Project" / "Final Paper" / etc. marker is present.
    if profile != "conservative":
        m = _DOCX_PREFIX_RE.match(refined)
        if m and len(refined) > m.end():
            tail = refined[m.end() :].strip()
            if tail:
                refined = tail

        # Also handle " - " explicit delimiter when prefix looks like
        # a document-type marker.
        if " - " in refined:
            head, _, tail = refined.partition(" - ")
            if _DOCX_PREFIX_RE.match(head + " ") and tail.strip():
                refined = tail.strip()

    return refined


def _is_skip_paragraph(para: str) -> bool:
    """Return True if a paragraph matches a byline / cover blurb / TOC pattern."""
    stripped = para.strip()
    if not stripped:
        return True
    # Byline: caps-heavy, has digit (affiliation), comma-separated.
    if _BYLINE_DETECT_RE.match(stripped):
        return True
    # Cover-page blurb keywords (case-insensitive).
    lowered = stripped.lower()
    for kw in _COVER_BLURB_KEYWORDS:
        if kw in lowered:
            return True
    # TOC line hints.
    if _TOC_LINE_HINTS_RE.search(stripped):
        return True
    return False


def _cleanup_abstract(text: str) -> str:
    """Apply post-selection cleanup: strip links, decode entities, truncate."""
    # Strip markdown links: [text](url) → text
    text = _MD_LINK_RE.sub(r"\1", text)
    # Decode HTML entities
    text = html.unescape(text)
    # Collapse whitespace runs
    text = re.sub(r"\s+", " ", text).strip()
    # Truncate to <= 400 chars at last sentence boundary
    if len(text) > 400:
        head = text[:400]
        # Find last sentence terminator inside the head
        matches = list(_SENTENCE_END_RE.finditer(head))
        if matches:
            cut = matches[-1].end()
            text = head[:cut].rstrip()
        else:
            # No sentence boundary — hard truncate
            text = head.rstrip()
    return text


def _split_body_paragraphs(body: str) -> list[str]:
    """Split body into paragraphs (blank-line separated, headings excluded)."""
    paras: list[str] = []
    for chunk in re.split(r"\n\s*\n", body):
        line = chunk.strip()
        if not line:
            continue
        # Skip heading lines
        if line.startswith("#"):
            continue
        paras.append(line)
    return paras


def refine_abstract(
    candidate: str | None,
    body: str,
    *,
    profile: Profile = "aggressive",
) -> str | None:
    """Replace candidate when it looks like a byline / cover blurb / TOC.

    Selection (in order):
      1. Body section under "## Abstract" / "## ABSTRACT" / "## Summary"
         (case-insensitive H2/H3) — take its first paragraph >= 80 chars.
      2. First non-skip paragraph >= 80 chars after H1 (current
         heuristic with skip-list applied).
      3. None.

    Skip patterns (move to the next paragraph if these match):
      - Author byline: starts with caps-heavy text, >= 3 commas, >= 1
        digit (affiliation marker).
      - Cover-page blurb: contains any of "feedback", "qr code",
        "scan the", "customer feedback form" (case-insensitive).
      - TOC line: contains "....\\d+" or "page \\d+" / "Page \\d+".

    Post-selection cleanup (always applied):
      - Strip inline markdown link syntax: [text](url) → text.
      - Decode HTML entities (html.unescape).
      - Truncate to <= 400 chars at last sentence boundary.

    Conservative profile: skip-list still active, but if no qualifying
    paragraph found returns None instead of falling through to a
    skipped paragraph. (Default aggressive returns the first non-skip
    even if it's a fallback.)
    """
    # Step 1: prefer "## Abstract" / "## Summary" body section.
    m = _ABSTRACT_HEADING_RE.search(body)
    if m:
        rest = body[m.end() :]
        # Take first non-empty paragraph until next heading or blank-line gap.
        for para in _split_body_paragraphs(rest):
            if len(para) >= 80 and not _is_skip_paragraph(para):
                return _cleanup_abstract(para)

    # Step 2: candidate. Apply skip-list; if candidate is clean, use it.
    if candidate and not _is_skip_paragraph(candidate):
        return _cleanup_abstract(candidate)

    # Candidate skipped or missing. Walk body paragraphs.
    for para in _split_body_paragraphs(body):
        # Skip the candidate itself if it appears verbatim in body.
        if candidate and para.strip() == candidate.strip():
            continue
        if _is_skip_paragraph(para):
            continue
        if len(para) < 80:
            continue
        return _cleanup_abstract(para)

    # Nothing acceptable.
    if profile == "conservative":
        return None
    # Aggressive fallback: if candidate exists but was skipped, return it
    # with cleanup applied (best-effort). Otherwise None.
    if candidate:
        return _cleanup_abstract(candidate)
    return None


def _normalize_author_name(name: str) -> str:
    """Title-case a name and strip stray digits/whitespace."""
    # Strip affiliation digits (trailing or interleaved)
    cleaned = _AFFIL_DIGITS_RE.sub("", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.")
    if not cleaned:
        return ""
    # Title-case if currently all-caps; else preserve.
    if cleaned.isupper():
        cleaned = cleaned.title()
    return cleaned


def _split_authors(text: str) -> list[str]:
    """Split a comma/and-separated author list into individual names."""
    # Replace " and " with comma to unify separators
    text = re.sub(r"\s+and\s+", ", ", text, flags=re.IGNORECASE)
    parts = [p.strip() for p in text.split(",")]
    # Filter empties and pure-digit affiliation tokens
    return [p for p in parts if p and not p.strip().isdigit()]


def _dedupe_authors(authors: list[str]) -> list[str]:
    """Order-preserving, case-insensitive deduplication."""
    seen: set[str] = set()
    out: list[str] = []
    for a in authors:
        key = re.sub(r"\s+", " ", a.strip().lower())
        key = re.sub(r"[^\w\s]", "", key)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def extract_authors(
    body: str,
    title_hint: str | None,
    arxiv_id: str | None = None,
    *,
    arxiv_lookup_enabled: bool = True,
    profile: Profile = "aggressive",
) -> list[str]:
    """Extract authors from body, optionally enriched with arxiv API.

    Detection chain (first match wins):
      1. arxiv_lookup(arxiv_id) result (when arxiv_id is set and
         arxiv_lookup_enabled is True; warns on failure).
      2. "Authors: <list>" or "Author: <name>" prefix line.
      3. "By <list>" prefix line near top of body (within first 20
         lines after H1).
      4. Academic byline pattern: caps-or-titlecase names, optional
         digit-affiliation markers, comma-separated, on the line(s)
         immediately after H1. Splits on commas-and-digit-groups.

    Returns deduplicated, order-preserving author list (max 20).
    Conservative profile: only patterns 1, 2, 3 (skips byline-pattern
    inference); returns [] when none match.
    """
    if not body:
        return []

    # Step 1: arxiv API
    if arxiv_id and arxiv_lookup_enabled:
        result = arxiv_lookup(arxiv_id)
        if result and result.get("authors"):
            authors = [_normalize_author_name(a) for a in result["authors"]]
            authors = [a for a in authors if a]
            return _dedupe_authors(authors)[:20]

    # Step 2 & 3: "Authors:" / "Author:" / "By" prefix — but only within
    # the first ~20 lines after H1 to avoid false positives on mid-doc
    # sentences like "By 'market governance mechanisms', we refer to ...".
    lines = body.splitlines()
    h1_idx = next((i for i, line in enumerate(lines) if line.startswith("# ")), -1)
    start = h1_idx + 1 if h1_idx >= 0 else 0
    head_block = "\n".join(lines[start : start + 20])
    m = _AUTHORS_PREFIX_RE.search(head_block)
    if m:
        raw = m.group(1).strip()
        names = [_normalize_author_name(n) for n in _split_authors(raw)]
        names = [n for n in names if n]
        # Sanity gate (applied after dedup):
        # - First entry must start with uppercase (rejects mid-doc sentences
        #   like "By 'market governance mechanisms', we refer to...")
        # - Each name <= 50 chars (rejects sentence-fragment captures)
        deduped = _dedupe_authors(names)[:20]
        if deduped and deduped[0][:1].isupper() and all(len(n) <= 50 for n in deduped):
            return deduped

    # Step 4: academic byline (aggressive only)
    if profile == "conservative":
        return []

    # Walk body lines and look for the academic byline pattern.
    lines = body.splitlines()
    h1_idx = -1
    for i, line in enumerate(lines):
        if line.startswith("# "):
            h1_idx = i
            break
    start = h1_idx + 1 if h1_idx >= 0 else 0
    for line in lines[start : start + 20]:
        stripped = line.strip()
        if not stripped:
            continue
        if _ACADEMIC_BYLINE_RE.match(stripped):
            names = [_normalize_author_name(n) for n in _split_authors(stripped)]
            names = [n for n in names if n]
            if names:
                return _dedupe_authors(names)[:20]
            break

    return []


def is_arxiv_filename(name: str) -> str | None:
    """Return arxiv ID if name matches arxiv pattern, else None.

    Accepts both new (\\d{4}.\\d{5}) and legacy (\\d{4}.\\d{4}) formats.
    Strips trailing "v\\d+" version qualifier.

    Examples:
      "2501.17755v1.pdf"    → "2501.17755"
      "1706.03762.pdf"      → "1706.03762"
      "report.pdf"          → None
    """
    if not name:
        return None
    # Use just the basename without leading directories
    base = name
    if "/" in base:
        base = base.rsplit("/", 1)[-1]
    if "\\" in base:
        base = base.rsplit("\\", 1)[-1]
    # Strip trailing .pdf (case-insensitive) so the regex can anchor.
    base_no_ext = base
    if base_no_ext.lower().endswith(".pdf"):
        base_no_ext = base_no_ext[: -len(".pdf")]
    # Search for the arxiv ID anywhere in the basename. Common filename
    # patterns: bare arxiv ID ("2501.17755v1.pdf"), prefixed with title
    # ("AI_Governance_through_Markets-2501.17755v1.pdf"), or trailing.
    # The negative-lookbehind (?<![0-9.]) prevents matching a number
    # embedded in a longer numeric sequence.
    m = re.search(r"(?<![0-9.])(\d{4}\.\d{4,5})(?:v\d+)?$", base_no_ext)
    if m:
        return m.group(1)
    # Also accept the arxiv ID anywhere in the basename when followed by
    # a non-digit/non-dot or end-of-string.
    m = re.search(r"(?<![0-9.])(\d{4}\.\d{4,5})(?:v\d+)?(?![0-9.])", base_no_ext)
    if m:
        return m.group(1)
    return None


def arxiv_lookup(arxiv_id: str, *, timeout: float = 5.0) -> dict | None:
    """Fetch metadata from the public arxiv API.

    On success returns:
      {
        "title": str,
        "authors": list[str],   # publication order
        "abstract": str,
        "date": str             # ISO YYYY-MM-DD
      }

    On any failure (SSRF block, network timeout, HTTP non-200, XML
    parse error, schema mismatch), emits a non-blocking warning via
    the pipeline's existing `add_warnings` channel and returns None.
    Conversion never fails because of arxiv unreachability.

    Endpoint: https://export.arxiv.org/api/query?id_list={arxiv_id}
    SSRF-guarded same as html.py (validate IPs against private/
    reserved/loopback). Timeout: 5s default. Single attempt, no retry.
    """
    from defusedxml.ElementTree import ParseError as _XmlParseError
    from defusedxml.ElementTree import fromstring as _xml_fromstring

    url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"

    def _warn(msg: str) -> None:
        # Lazy import to avoid circular dependency at module load time.
        try:
            from any2md.converters import add_warnings

            add_warnings([msg])
        except Exception:  # noqa: BLE001
            pass

    # Fetch via shared SSRF-safe helper (handles scheme, IP-class
    # validation, and per-hop revalidation across redirects).
    try:
        from any2md._http import safe_fetch
    except Exception as e:  # noqa: BLE001
        _warn(_logging.safe_oneline(f"arxiv lookup _http import failed: {e}"))
        return None
    body, _headers, err = safe_fetch(url)
    if err:
        _warn(_logging.safe_oneline(f"arxiv lookup blocked or failed: {err}"))
        return None
    if body is None:
        return None
    data = body

    try:
        root = _xml_fromstring(data)
    except _XmlParseError as e:
        _warn(
            _logging.safe_oneline(f"arxiv lookup XML parse error for {arxiv_id}: {e}")
        )
        return None

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        _warn(_logging.safe_oneline(f"arxiv lookup: no entry for {arxiv_id}"))
        return None

    title_el = entry.find("atom:title", ns)
    summary_el = entry.find("atom:summary", ns)
    published_el = entry.find("atom:published", ns)
    author_els = entry.findall("atom:author/atom:name", ns)

    title = (title_el.text or "").strip() if title_el is not None else ""
    abstract = (summary_el.text or "").strip() if summary_el is not None else ""
    date = ""
    if published_el is not None and published_el.text:
        # ISO 8601 → first 10 chars (YYYY-MM-DD)
        date = published_el.text.strip()[:10]
    authors = [(a.text or "").strip() for a in author_els if a.text]

    if not title and not authors and not abstract:
        _warn(_logging.safe_oneline(f"arxiv lookup: empty schema for {arxiv_id}"))
        return None

    return {
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "date": date,
    }
