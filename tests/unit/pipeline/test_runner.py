"""Tests for pipeline composition and PipelineOptions."""

from any2md.pipeline import PipelineOptions, run


def test_pipeline_options_defaults():
    opts = PipelineOptions()
    assert opts.profile == "aggressive"
    assert opts.ocr_figures is False
    assert opts.save_images is False
    assert opts.strip_links is False
    assert opts.strict is False


def test_pipeline_options_frozen():
    import dataclasses

    opts = PipelineOptions()
    assert dataclasses.is_dataclass(opts)
    # Frozen dataclasses raise on attribute assignment
    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        opts.profile = "conservative"  # type: ignore[misc]


def test_run_returns_text_and_warnings_tuple():
    text, warnings = run("hello\n", "text", PipelineOptions())
    assert isinstance(text, str)
    assert isinstance(warnings, list)


def test_run_invalid_lane_raises():
    import pytest

    with pytest.raises(ValueError, match="lane"):
        run("hello", "bogus", PipelineOptions())  # type: ignore[arg-type]


def test_pipeline_options_has_high_fidelity_field():
    opts = PipelineOptions(high_fidelity=True)
    assert opts.high_fidelity is True


def test_pipeline_options_high_fidelity_default_false():
    opts = PipelineOptions()
    assert opts.high_fidelity is False


def test_pipeline_options_backend_default_none():
    assert PipelineOptions().backend is None


def test_pipeline_options_backend_can_be_set():
    assert PipelineOptions(backend="docling").backend == "docling"
    assert PipelineOptions(backend="pymupdf4llm").backend == "pymupdf4llm"
    assert PipelineOptions(backend="mammoth").backend == "mammoth"


def test_pipeline_options_arxiv_lookup_default_true():
    assert PipelineOptions().arxiv_lookup is True


def test_pipeline_options_arxiv_lookup_can_be_set_false():
    assert PipelineOptions(arxiv_lookup=False).arxiv_lookup is False
