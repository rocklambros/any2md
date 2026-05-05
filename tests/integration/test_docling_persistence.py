"""Integration tests for the persistent DocumentConverter cache (v1.1.0).

Gated by `pytest.mark.skipif(not has_docling())` per existing pattern
in `tests/integration/test_pdf_docling.py`.
"""
from __future__ import annotations

import pytest

from any2md._docling import has_docling
from any2md._docling_cache import stats
from any2md.converters.docx import convert_docx
from any2md.converters.pdf import convert_pdf
from any2md.pipeline import PipelineOptions


pytestmark = pytest.mark.skipif(
    not has_docling(),
    reason="docling not installed (test runs only when [high-fidelity] is installed)",
)


def test_persistence_happy_path(fixture_dir, tmp_output_dir):
    """AC#1: two consecutive convert_pdf calls share the same
    DocumentConverter — exactly one model_loads increment."""
    pdf = fixture_dir / "multi_column.pdf"
    options = PipelineOptions(high_fidelity=True)

    convert_pdf(pdf, tmp_output_dir, options=options, force=True)
    convert_pdf(pdf, tmp_output_dir, options=options, force=True)

    s = stats()
    assert s.model_loads == 1, f"expected 1 model load, got {s.model_loads}"
    assert s.cache_hits >= 1


def test_mixed_format_batch(fixture_dir, tmp_output_dir):
    """AC#2: PDF, DOCX, PDF, DOCX — exactly two model loads, no
    eviction-thrash."""
    pdf = fixture_dir / "multi_column.pdf"
    docx = fixture_dir / "simple.docx"
    if not docx.exists():
        # Some test fixture sets may not include a docx; skip in that case
        pytest.skip("simple.docx fixture not present")
    options = PipelineOptions(high_fidelity=True)

    convert_pdf(pdf, tmp_output_dir, options=options, force=True)
    convert_docx(docx, tmp_output_dir, options=options, force=True)
    convert_pdf(pdf, tmp_output_dir, options=options, force=True)
    convert_docx(docx, tmp_output_dir, options=options, force=True)

    s = stats()
    assert s.model_loads == 2, f"expected 2 model loads, got {s.model_loads}"


def test_convert_failure_evicts_and_rebuilds(
    fixture_dir, tmp_output_dir, monkeypatch
):
    """AC#3: a convert() exception triggers slot eviction; next call
    rebuilds. Verified by stats counters."""
    pdf = fixture_dir / "multi_column.pdf"
    options = PipelineOptions(high_fidelity=True)

    # First call — populates cache, succeeds normally
    convert_pdf(pdf, tmp_output_dir, options=options, force=True)
    pre_loads = stats().model_loads
    pre_evicts = stats().cache_evictions

    # Monkeypatch convert() on the cached instance to raise once.
    from any2md._docling_cache import _get_instance, _hash_opts, _Key
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    pipeline_opts = PdfPipelineOptions(
        do_ocr=options.ocr_figures,
        do_table_structure=True,
        generate_picture_images=options.save_images,
    )
    inst = _get_instance()
    key = _Key("pdf", _hash_opts(pipeline_opts))
    cached = inst._store[key]

    call_count = {"n": 0}
    original_convert = cached.convert

    def flaky_convert(path):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated Docling failure")
        return original_convert(path)

    monkeypatch.setattr(cached, "convert", flaky_convert)

    # Convert — first call's flaky_convert raises → upstream catches
    # and falls back to pymupdf4llm; cache slot evicted.
    convert_pdf(pdf, tmp_output_dir, options=options, force=True)

    s = stats()
    assert s.convert_failures >= 1
    assert s.cache_evictions > pre_evicts

    # Convert again — cache miss → rebuild
    convert_pdf(pdf, tmp_output_dir, options=options, force=True)
    s2 = stats()
    assert s2.model_loads > pre_loads, (
        f"expected rebuild after eviction; loads went {pre_loads} → {s2.model_loads}"
    )
