"""Frontmatter emission errors must fail one file, not the batch.

Every converter calls ``compose()`` inside its per-file error boundary.
An override the emitter cannot render has to come back as ``False``
with a FAIL line, so the CLI loop moves on to the next file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from any2md.converters.docx import convert_docx
from any2md.converters.html import convert_html
from any2md.converters.pdf import convert_pdf
from any2md.converters.txt import convert_txt
from any2md.pipeline import PipelineOptions

_CASES = [
    (convert_txt, "ligatures_and_softhyphens.txt", None),
    (convert_html, "web_page.html", None),
    (convert_docx, "table_heavy.docx", "mammoth"),
    (convert_pdf, "multi_column.pdf", "pymupdf4llm"),
]


@pytest.mark.parametrize(
    ("convert", "fixture", "backend"),
    _CASES,
    ids=[c[1] for c in _CASES],
)
def test_emission_error_is_a_per_file_failure(
    convert, fixture, backend, fixture_dir: Path, tmp_path: Path, capsys
):
    bad = PipelineOptions(backend=backend, frontmatter_overrides={"a": {"b": object()}})
    assert convert(fixture_dir / fixture, tmp_path / "bad", options=bad) is False
    assert f"FAIL: {fixture}" in capsys.readouterr().err

    # The next file in the batch converts normally after the failure.
    good = PipelineOptions(backend=backend)
    assert convert(fixture_dir / fixture, tmp_path / "good", options=good) is True
