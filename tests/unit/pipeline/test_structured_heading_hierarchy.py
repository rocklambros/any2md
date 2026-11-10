"""Tests for S4 — enforce_heading_hierarchy."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.structured import enforce_heading_hierarchy


def test_clean_doc_is_unchanged():
    text = "# Title\n\n## Sec\n\n### Sub\n"
    assert enforce_heading_hierarchy(text, PipelineOptions()) == text


def test_promotes_first_heading_when_no_h1():
    text = "## First Heading\n\n### Sub\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert out.startswith("# First Heading\n")


def test_demotes_subsequent_h1():
    text = "# A\n\nbody\n\n# B\n\nmore\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert out.count("# A") == 1
    assert "## B" in out


def test_repairs_skipped_levels():
    text = "# A\n\n#### Deep\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    # H1 → H4 became H1 → H2 (one level deeper than H1)
    assert "## Deep" in out


def test_no_headings_is_noop():
    text = "Plain body, no headings.\n"
    assert enforce_heading_hierarchy(text, PipelineOptions()) == text


def _levels(text: str) -> list[str]:
    """Return the heading lines of ``text`` in order."""
    return [line for line in text.split("\n") if line.startswith("#")]


def test_sibling_h3s_under_h1_stay_siblings():
    text = "# T\n\n### A\n\n### B\n\n### C\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert out == "# T\n\n## A\n\n## B\n\n## C\n"


def test_nesting_under_skipped_level_is_kept():
    text = "# T\n\n### A\n\n#### A1\n\n### B\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert _levels(out) == ["# T", "## A", "### A1", "## B"]


def test_deep_skip_then_shallower_heading():
    text = "# T\n\n#### Deep\n\n## Back\n\n###### Deeper\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert _levels(out) == ["# T", "## Deep", "## Back", "### Deeper"]


def test_no_h1_promotes_first_and_ranks_rest():
    text = "### A\n\n##### A1\n\n### B\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert _levels(out) == ["# A", "## A1", "## B"]


def test_repeated_h1_children_rank_under_demoted_h1():
    text = "# A\n\n### a1\n\n# B\n\n#### b1\n\n#### b2\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert _levels(out) == ["# A", "## a1", "## B", "### b1", "### b2"]


def test_headings_inside_fenced_code_are_untouched():
    text = (
        "# T\n\n"
        "```markdown\n### not a heading\n# also not\n```\n\n"
        "~~~\n#### still code\n~~~\n\n"
        "### A\n"
    )
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert "```markdown\n### not a heading\n# also not\n```" in out
    assert "~~~\n#### still code\n~~~" in out
    assert out.endswith("\n## A\n")


def test_fenced_heading_does_not_count_as_h1():
    text = "```\n# code comment\n```\n\n## Real\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert out == "```\n# code comment\n```\n\n# Real\n"


def test_four_backtick_fence_survives_shorter_and_tilde_lines():
    text = "# T\n\n````\n```\n### code\n~~~\n### code\n````\n\n### Real\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert "````\n```\n### code\n~~~\n### code\n````" in out
    assert out.endswith("\n## Real\n")


def test_tilde_fence_not_closed_by_backticks():
    text = "# T\n\n~~~\n```\n### code\n~~~\n\n### Real\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert "```\n### code\n~~~" in out
    assert out.endswith("\n## Real\n")


def test_fence_with_trailing_text_does_not_close():
    text = "# T\n\n```\n``` not a closer\n### code\n```\n\n### Real\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert "``` not a closer\n### code\n```" in out
    assert out.endswith("\n## Real\n")


def test_backtick_info_string_with_backtick_is_not_a_fence():
    text = "# T\n\n``` a`b\n\n### Real\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert out.endswith("\n## Real\n")


def test_tilde_info_string_may_hold_backticks():
    text = "# T\n\n~~~ a`b\n### code\n~~~\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert "~~~ a`b\n### code\n~~~" in out


def test_top_level_indented_code_is_not_a_fence():
    text = "# T\n\n    ```\n\n### Real\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert out == "# T\n\n    ```\n\n## Real\n"


def test_thematic_break_does_not_open_a_list():
    text = "# T\n\n* * *\n\n    ```\n\n### Real\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert out == "# T\n\n* * *\n\n    ```\n\n## Real\n"


def test_list_fence_ends_with_its_item():
    text = "# T\n\n- ```\n  code\n\n### Real\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert out == "# T\n\n- ```\n  code\n\n## Real\n"


def test_fence_after_several_list_markers():
    text = "# T\n\n- - ```\n    code\n    ```\n\n### Real\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert out == "# T\n\n- - ```\n    code\n    ```\n\n## Real\n"


def test_tab_after_list_marker_sets_content_column():
    text = "# T\n\n- \titem\n\n  ```\n### code\n```\n\n### Real\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert out == "# T\n\n- \titem\n\n  ```\n### code\n```\n\n## Real\n"


def test_ordered_marker_past_one_does_not_interrupt_paragraph():
    # No H1 in the input, so S4 promotes "Real", the first heading, to H1.
    text = "Paragraph\n2. not a list\n\n   ```\n### code\n```\n\n### Real\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert out == "Paragraph\n2. not a list\n\n   ```\n### code\n```\n\n# Real\n"


def test_nbsp_after_closer_does_not_close():
    text = "# T\n\n```\n```\u00a0\n### code\n```\n\n### Real\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert out == "# T\n\n```\n```\u00a0\n### code\n```\n\n## Real\n"


def test_fence_inside_html_block_is_not_an_opener():
    text = "# T\n\n<pre>\n```\n</pre>\n\n### Real\n"
    out = enforce_heading_hierarchy(text, PipelineOptions())
    assert out == "# T\n\n<pre>\n```\n</pre>\n\n## Real\n"
