"""any2md/heuristics.py

Field-derivation refinements that go beyond what raw extractors give us.
Every function is pure (input → output, no side effects) except
arxiv_lookup which makes one network call and emits a warning on failure.

Called from frontmatter.compose() and converter modules to refine
candidate values before YAML emission.
"""

from __future__ import annotations

import re
from typing import NamedTuple

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
_COVER_PAGE_H1_VALUES = frozenset({
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
})

# H1 / H2 line detectors (markdown ATX style)
_H1_LINE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_H2_LINE_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)

# DOCX line-break course-code / document-type prefix detector. Matches
# strings like "COMP 4441 Final Project " (course code followed by
# document-type marker). The trailing space is required so we only
# split when there's content after the marker.
_DOCX_PREFIX_RE = re.compile(
    r"^(?:[A-Z]{2,5}\s*\d{2,5}\s+)?"
    r"(?:Final Project|Final Paper|Term Paper|Thesis|Dissertation|"
    r"Research Paper|Capstone Project)\s+",
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

    # Cover-page boilerplate skip (both profiles)
    if refined.lower() in _COVER_PAGE_H1_VALUES:
        m = _H2_LINE_RE.search(body)
        if m:
            return m.group(1).strip()

    # Wikipedia namespace prefix strip (aggressive only)
    if profile != "conservative" and source_url:
        try:
            from urllib.parse import urlparse
            host = (urlparse(source_url).hostname or "").lower()
        except Exception:  # noqa: BLE001
            host = ""
        if host.endswith("wikipedia.org"):
            for prefix in ("Wikipedia:", "WP:"):
                if refined.startswith(prefix):
                    refined = refined[len(prefix):].strip()
                    break

    # DOCX line-break course-code / document-type prefix split
    # (aggressive only). Best-effort: only fires when an explicit
    # "Final Project" / "Final Paper" / etc. marker is present.
    if profile != "conservative":
        m = _DOCX_PREFIX_RE.match(refined)
        if m and len(refined) > m.end():
            tail = refined[m.end():].strip()
            if tail:
                refined = tail

        # Also handle " - " explicit delimiter when prefix looks like
        # a document-type marker.
        if " - " in refined:
            head, _, tail = refined.partition(" - ")
            if _DOCX_PREFIX_RE.match(head + " ") and tail.strip():
                refined = tail.strip()

    return refined
