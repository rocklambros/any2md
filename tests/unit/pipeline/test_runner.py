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
