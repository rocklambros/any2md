"""Tests for frontmatter.compose() — SSRM-compatible output."""

import yaml

from any2md.frontmatter import SourceMeta, compose
from any2md.pipeline import PipelineOptions


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Helper: split a frontmatter+body string into (yaml_dict, body_str)."""
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    fm = yaml.safe_load(text[4:end])
    body = text[end + 5 :]
    # compose() emits a blank-line separator between frontmatter and body;
    # strip one leading newline so body matches the original (post-norm) body.
    if body.startswith("\n"):
        body = body[1:]
    return fm, body


def _meta(**overrides) -> SourceMeta:
    base = dict(
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
    base.update(overrides)
    return SourceMeta(**base)


def test_compose_emits_required_ssrm_fields():
    body = "# Title\n\nbody\n"
    out = compose(body, _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    for key in [
        "title",
        "document_id",
        "version",
        "date",
        "status",
        "document_type",
        "content_domain",
        "authors",
        "organization",
        "generation_metadata",
        "content_hash",
    ]:
        assert key in fm, f"missing required field: {key}"


def test_compose_status_is_draft():
    out = compose("# T\n\nbody\n", _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm["status"] == "draft"


def test_compose_document_type_and_content_domain_are_empty():
    out = compose("# T\n\nbody\n", _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm["document_type"] == ""
    assert fm["content_domain"] == []


def test_compose_document_id_empty_by_default():
    out = compose("# T\n\nbody\n", _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm["document_id"] == ""


def test_compose_authored_by_unknown():
    out = compose("# T\n\nbody\n", _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm["generation_metadata"]["authored_by"] == "unknown"


def test_compose_content_hash_matches_body():
    body = "# T\n\nbody\n"
    out = compose(body, _meta(), PipelineOptions())
    fm, body_out = _split_frontmatter(out)
    from any2md.frontmatter import compute_content_hash

    assert fm["content_hash"] == compute_content_hash(body_out)


def test_compose_includes_source_file_extension_field():
    out = compose("# T\n\nbody\n", _meta(source_file="report.pdf"), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm["source_file"] == "report.pdf"


def test_compose_uses_source_url_when_provided():
    out = compose(
        "# T\n\nbody\n",
        _meta(source_file=None, source_url="https://example.com/article"),
        PipelineOptions(),
    )
    fm, _ = _split_frontmatter(out)
    assert fm["source_url"] == "https://example.com/article"


def test_compose_token_estimate_present_and_positive():
    out = compose("# T\n\n" + "x" * 100 + "\n", _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm["token_estimate"] >= 25


def test_compose_skips_abstract_for_short_doc():
    short = "# T\n\nshort body.\n"
    out = compose(short, _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert "abstract_for_rag" not in fm or fm.get("abstract_for_rag") in (None, "")


def test_compose_includes_abstract_for_long_doc():
    big = (
        "# T\n\n"
        + "This is a long abstract sentence that should be picked. " * 100
        + "\n"
    )
    out = compose(big, _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm.get("abstract_for_rag")
    assert len(fm["abstract_for_rag"]) <= 400


def test_compose_body_ends_with_lf():
    out = compose("# T\n\nbody\n", _meta(), PipelineOptions())
    assert out.endswith("\n")
    assert "\r" not in out


def test_compose_body_is_nfc():
    import unicodedata

    decomposed = unicodedata.normalize("NFD", "café")  # e + combining acute
    composed = unicodedata.normalize("NFC", "café")  # precomposed é
    assert decomposed != composed  # sanity: forms differ
    body = f"# T\n\n{decomposed}\n"
    out = compose(body, _meta(), PipelineOptions())
    _, body_out = _split_frontmatter(out)
    assert composed in body_out
    assert decomposed not in body_out


def test_compose_deterministic_for_same_input():
    body = "# Title\n\nstable body content here.\n"
    a = compose(body, _meta(date="2026-04-26"), PipelineOptions())
    b = compose(body, _meta(date="2026-04-26"), PipelineOptions())
    assert a == b


def test_compose_emits_produced_by_when_set():
    out = compose(
        "# T\n\nbody\n",
        _meta(produced_by="Adobe InDesign 16.2"),
        PipelineOptions(),
    )
    fm, _ = _split_frontmatter(out)
    assert fm["produced_by"] == "Adobe InDesign 16.2"


def test_compose_omits_produced_by_when_none():
    out = compose(
        "# T\n\nbody\n",
        _meta(produced_by=None),
        PipelineOptions(),
    )
    fm, _ = _split_frontmatter(out)
    assert "produced_by" not in fm


def test_compose_uses_heuristics_refine_title():
    """Cover-page boilerplate H1 is replaced by the first H2."""
    body = "# INTERNATIONAL STANDARD\n\n## Real Title\n\nSome content here.\n"
    out = compose(body, _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm["title"] == "Real Title"


def test_compose_uses_heuristics_refine_abstract():
    """Byline-style first paragraph is skipped in favor of an explicit
    '## Abstract' section's content."""
    # Build a body long enough to clear the 500-token threshold so that
    # extract_abstract / refine_abstract actually run.
    real_abstract = (
        "This is the genuine abstract paragraph that explains what the "
        "paper is about and contains enough characters to satisfy the "
        "minimum length requirement of eighty characters."
    )
    filler = "Section content. " * 200
    body = (
        "# Paper Title\n\n"
        "JANE DOE1, JOHN SMITH2, AUTHOR THREE3, contact@example.com\n\n"
        "## Abstract\n\n"
        f"{real_abstract}\n\n"
        "## Introduction\n\n"
        f"{filler}\n"
    )
    out = compose(body, _meta(), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm.get("abstract_for_rag")
    assert "genuine abstract paragraph" in fm["abstract_for_rag"]


def test_compose_extract_authors_when_meta_empty():
    """When meta.authors is empty, the heuristics chain extracts from body."""
    body = "# Paper Title\n\nAuthors: Alice, Bob\n\nMore body content.\n"
    out = compose(body, _meta(authors=[]), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm["authors"] == ["Alice", "Bob"]


def test_compose_meta_authors_takes_priority():
    """When meta.authors is non-empty, body byline is ignored."""
    body = "# Paper Title\n\nAuthors: Alice\n\nMore body content.\n"
    out = compose(body, _meta(authors=["Bob"]), PipelineOptions())
    fm, _ = _split_frontmatter(out)
    assert fm["authors"] == ["Bob"]
