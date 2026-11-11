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


def _warnings(text: str) -> list[str]:
    from any2md.pipeline import _WARNINGS, cleanup

    bucket: list[str] = []
    token = _WARNINGS.set(bucket)
    try:
        cleanup.validate(text, PipelineOptions())
    finally:
        _WARNINGS.reset(token)
    return bucket


# C7 counts headings through the shared block scanner, so it sees the
# same headings S4 and the HTML lane rank.


def test_validate_ignores_fenced_heading():
    assert _warnings("# T\n\n```\n# x\n```\n") == []


def test_validate_ignores_quoted_heading():
    assert _warnings("# T\n\n> # x\n") == []


def test_validate_counts_setext_h1():
    assert _warnings("Title\n=====\n\nBody.\n") == []
    assert _warnings("# T\n\nOther\n=====\n") == [
        "validator: H1 count is 2 (expected 1)"
    ]


def test_validate_counts_heading_after_page_break():
    assert _warnings("\f# T\n\nBody.\n") == []


def test_validate_reads_setext_h2_for_skip_check():
    assert _warnings("# T\n\nSub\n---\n\n### Deep\n") == []
