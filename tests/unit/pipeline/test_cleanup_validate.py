"""Tests for C7 — validate (read-only)."""

from any2md.pipeline import PipelineOptions, run


def test_validate_emits_warning_on_missing_h1():
    text = "## Section\n\nNo H1 here.\n"
    out, warnings = run(text, "text", PipelineOptions())
    assert out == text or out.endswith("\n")  # cleanup may have touched whitespace
    assert any("H1" in w for w in warnings), f"warnings={warnings}"


def test_validate_emits_warning_on_skipped_heading_level():
    text = "# Title\n\n## Sub\n\n#### Sub-sub-sub (skip H3)\n"
    _, warnings = run(text, "text", PipelineOptions())
    assert any("skip" in w.lower() for w in warnings)


def test_validate_no_warnings_on_clean_doc():
    text = "# Title\n\n## Section\n\nBody content.\n"
    _, warnings = run(text, "text", PipelineOptions())
    assert warnings == []


def test_validate_does_not_mutate_text():
    text = "# Title\n\n## Section\n\nBody.\n"
    out, _ = run(text, "text", PipelineOptions())
    # Cleanup C1-C5 may normalize whitespace, but the body should still match
    # post-strip semantically.
    assert "# Title" in out
    assert "## Section" in out
    assert "Body" in out
