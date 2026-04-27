"""Tests for SourceMeta and frontmatter module skeleton."""

import dataclasses

from any2md.frontmatter import (
    SourceMeta,
    derive_title,
    estimate_tokens,
    extract_abstract,
    recommend_chunk_level,
)


def test_source_meta_has_required_fields():
    fields = {f.name for f in dataclasses.fields(SourceMeta)}
    expected = {
        "title_hint",
        "authors",
        "organization",
        "produced_by",
        "date",
        "keywords",
        "pages",
        "word_count",
        "source_file",
        "source_url",
        "extracted_via",
        "lane",
    }
    assert expected <= fields, f"missing fields: {expected - fields}"


def test_source_meta_defaults_are_safe():
    meta = SourceMeta(
        title_hint=None,
        authors=[],
        organization=None,
        date=None,
        keywords=[],
        pages=None,
        word_count=None,
        source_file="x.txt",
        source_url=None,
        doc_type="txt",
        extracted_via="heuristic",
        lane="text",
    )
    assert meta.lane == "text"
    assert meta.extracted_via == "heuristic"
    assert meta.doc_type == "txt"


def test_estimate_tokens_zero_on_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_ceil_chars_over_4():
    # 4 chars -> 1 token, 5 chars -> 2 tokens (ceil)
    assert estimate_tokens("a" * 4) == 1
    assert estimate_tokens("a" * 5) == 2
    assert estimate_tokens("a" * 8) == 2


def test_chunk_level_h2_when_no_h2_sections():
    assert recommend_chunk_level("# Title\n\nbody only\n") == "h2"


def test_chunk_level_h2_when_all_sections_short():
    body = "# Title\n\n## A\n\nshort\n\n## B\n\nshort\n"
    assert recommend_chunk_level(body) == "h2"


def test_chunk_level_h3_when_any_section_exceeds_1500_tokens():
    # 1500 tokens * 4 chars/token = 6000 chars
    big = "x" * 6500
    body = f"# Title\n\n## A\n\n{big}\n\n## B\n\nshort\n"
    assert recommend_chunk_level(body) == "h3"


def test_abstract_first_paragraph_after_h1():
    body = (
        "# Title\n\n"
        "This is the first paragraph and is reasonably long enough to be "
        "considered an abstract candidate.\n\n"
        "Second paragraph should be ignored.\n"
    )
    abstract = extract_abstract(body)
    assert abstract is not None
    assert "first paragraph" in abstract
    assert "Second paragraph" not in abstract


def test_abstract_skips_short_paragraphs():
    body = (
        "# Title\n\n"
        "short.\n\n"
        "This is a longer paragraph that should be picked because it exceeds "
        "the 80 character minimum threshold for the abstract heuristic.\n"
    )
    abstract = extract_abstract(body)
    assert abstract is not None
    assert "longer paragraph" in abstract


def test_abstract_truncates_at_400_chars_at_sentence_boundary():
    long_para = "Sentence one is here. " * 30  # ~660 chars
    body = f"# Title\n\n{long_para}\n"
    abstract = extract_abstract(body)
    assert abstract is not None
    assert len(abstract) <= 400
    assert abstract.endswith(".")


def test_abstract_returns_none_when_no_paragraph_after_h1():
    body = "# Title\n\n## Section\n\nbody under section.\n"
    # No bare paragraph between H1 and the next heading.
    assert extract_abstract(body) is None


def test_derive_title_uses_first_h1():
    body = "# My Title\n\nbody\n"
    assert derive_title(body, title_hint=None, fallback="x.pdf") == "My Title"


def test_derive_title_falls_back_to_hint_when_no_h1():
    body = "## No H1\n\nbody\n"
    assert derive_title(body, title_hint="Hint Title", fallback="x.pdf") == "Hint Title"


def test_derive_title_falls_back_to_filename_when_neither():
    body = "no headings here\n"
    assert derive_title(body, title_hint=None, fallback="my_doc.pdf") == "my doc"


def test_derive_title_strips_markdown_emphasis_in_h1():
    body = "# **Bold Title** _emphasis_\n"
    assert derive_title(body, title_hint=None, fallback="x") == "Bold Title emphasis"
