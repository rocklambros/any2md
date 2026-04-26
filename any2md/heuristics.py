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
