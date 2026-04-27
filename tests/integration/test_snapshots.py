"""Snapshot tests: golden outputs for synthetic fixtures.

Snapshots are committed under tests/fixtures/snapshots/. To regenerate
after an intentional change run:
    UPDATE_SNAPSHOTS=1 pytest tests/integration/test_snapshots.py

Backend-variant snapshots (PDF/DOCX): when Docling is installed the
extracted markdown differs from the pymupdf4llm/mammoth output, so PDF
and DOCX fixtures use a `<stem>.docling.md` snapshot when Docling is
present and a `<stem>.fallback.md` snapshot otherwise. HTML and TXT
remain backend-independent (`<stem>.md`).

NOTE: The `.fallback.md` snapshots committed in this branch were carried
over from the Phase 1 single-snapshot scheme and may be stale relative
to the current converter output (the Docling-fixture-fix in Batch D
changed how figures/captions surface even on the fallback path). They
are kept for CI runs without Docling installed; if those runs fail with
diff, regenerate with `UPDATE_SNAPSHOTS=1` in a Docling-less env. A
clean refresh is deferred to a follow-up task — see CHANGELOG and the
Phase 2 plan Task 12 for context.
"""

import os
import re
from pathlib import Path

import pytest

from any2md._docling import has_docling
from any2md.converters.docx import convert_docx
from any2md.converters.html import convert_html
from any2md.converters.pdf import convert_pdf
from any2md.converters.txt import convert_txt
from any2md.pipeline import PipelineOptions

# (lane_label, converter, backend_dependent)
SNAPSHOTS = {
    "web_page.html": ("html", convert_html, False),
    "ligatures_and_softhyphens.txt": ("txt", convert_txt, False),
    "multi_column.pdf": ("pdf", convert_pdf, True),
    "table_heavy.docx": ("docx", convert_docx, True),
}


_DATE_RE = re.compile(r'^date: ".*?"', re.MULTILINE)
_HASH_RE = re.compile(r'^content_hash: ".*?"', re.MULTILINE)


def _normalize(text: str) -> str:
    """Strip volatile fields (date, content_hash) so snapshots are stable."""
    text = _DATE_RE.sub('date: "<volatile>"', text)
    text = _HASH_RE.sub('content_hash: "<volatile>"', text)
    return text


@pytest.mark.parametrize("fixture_name", list(SNAPSHOTS))
def test_snapshot(fixture_name, fixture_dir, snapshot_dir, tmp_output_dir):
    _, convert, backend_dependent = SNAPSHOTS[fixture_name]
    ok = convert(
        fixture_dir / fixture_name,
        tmp_output_dir,
        options=PipelineOptions(),
        force=True,
    )
    assert ok
    out = next(tmp_output_dir.glob("*.md"))
    actual = _normalize(out.read_text(encoding="utf-8"))

    stem = Path(fixture_name).stem
    if backend_dependent:
        suffix = ".docling" if has_docling() else ".fallback"
        snap_path = snapshot_dir / f"{stem}{suffix}.md"
    else:
        snap_path = snapshot_dir / f"{stem}.md"

    if os.environ.get("UPDATE_SNAPSHOTS"):
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(actual, encoding="utf-8")
        return

    expected = snap_path.read_text(encoding="utf-8") if snap_path.exists() else None
    if expected is None:
        pytest.fail(
            f"Snapshot missing: {snap_path}. Run UPDATE_SNAPSHOTS=1 pytest to create."
        )
    assert actual == expected, "Snapshot diff. Inspect or run UPDATE_SNAPSHOTS=1."
