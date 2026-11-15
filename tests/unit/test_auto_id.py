"""Unit tests for ``--auto-id`` document_id generation.

The id pattern is ``{PREFIX}-{YYYY}-{TYPE}-{SEQ}`` and must match the SAGE
v1.0-RC1 rule ``^[A-Z0-9]+-\\d{4}-[A-Z]{2,4}-\\d{3,}$``. SEQ is the first
8 hex chars of the body's content hash read as a 32-bit integer and
zero-padded to 10 decimal digits, so two bodies that share a
``content_hash`` share an ``id``. YYYY is the year of the emitted ``date``
field, never the clock.
"""

from __future__ import annotations

import re
from datetime import date

import pytest
import yaml

from any2md.frontmatter import (
    SourceMeta,
    compose,
    compute_content_hash,
    generate_document_id,
)
from any2md.pipeline import PipelineOptions

SAGE_ID_RE = re.compile(r"^[A-Z0-9]+-\d{4}-[A-Z]{2,4}-\d{3,}$")

# Hex-heavy and digit-only bodies: under v1.2.2 the first produced hex
# letters in SEQ. A spread of bodies guards against a lucky all-digit hash.
_BODIES = ["# Title\n\nbody.\n", "x", "body one", "body two", "", "é\r\n"]


def _meta(**overrides) -> SourceMeta:
    base = dict(
        title_hint=None,
        authors=[],
        organization=None,
        date="2024-06-01",
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


def _frontmatter(text: str) -> dict:
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end])


def _freeze_today(monkeypatch, year: int) -> None:
    """Pin ``date.today()`` as seen by ``any2md.frontmatter``."""

    class _Frozen(date):
        @classmethod
        def today(cls):
            return cls(year, 1, 2)

    monkeypatch.setattr("any2md.frontmatter._date_cls", _Frozen)


@pytest.mark.parametrize("body", _BODIES)
@pytest.mark.parametrize(
    ("prefix", "type_code"), [("LOCAL", "DOC"), ("CSA", "GD"), ("ACME1", "GUID")]
)
def test_generated_id_matches_sage_regex(body, prefix, type_code):
    doc_id = generate_document_id(body, year=2026, prefix=prefix, type_code=type_code)
    assert SAGE_ID_RE.match(doc_id), doc_id


def test_default_prefix_and_type_code():
    assert generate_document_id("x", year=2026).startswith("LOCAL-2026-DOC-")


def test_known_vector():
    """Fixed body → exact id. SHA-256 prefix 192f455c = 422528348."""
    doc_id = generate_document_id(
        "# Title\n\nbody.\n", year=2025, prefix="CSA", type_code="GD"
    )
    assert doc_id == "CSA-2025-GD-0422528348"


def test_seq_is_ten_digits():
    seq = generate_document_id("x", year=2026).rsplit("-", 1)[1]
    assert len(seq) == 10
    assert seq.isdigit()


def test_document_id_deterministic():
    body = "# Title\n\nbody.\n"
    assert generate_document_id(body, year=2026) == generate_document_id(
        body, year=2026
    )


def test_document_id_changes_with_body():
    assert generate_document_id("body one", year=2026) != generate_document_id(
        "body two", year=2026
    )


def test_bodies_sharing_content_hash_share_id():
    """CRLF and LF bodies hash the same, so they share an id."""
    assert generate_document_id("a\r\nb", year=2026) == generate_document_id(
        "a\nb", year=2026
    )


@pytest.mark.parametrize(
    ("prefix", "type_code"),
    [
        ("csa", "GD"),
        ("", "GD"),
        ("CS-A", "GD"),
        ("CSA", "gd"),
        ("CSA", "G"),
        ("CSA", "GUIDE"),
        ("CSA", "G1"),
        ("CSA", ""),
    ],
)
def test_generate_rejects_nonconforming_prefix_or_type_code(prefix, type_code):
    with pytest.raises(ValueError):
        generate_document_id("x", year=2026, prefix=prefix, type_code=type_code)


@pytest.mark.parametrize("year", [-1, 10000, 99999])
def test_generate_rejects_year_outside_four_digits(year):
    with pytest.raises(ValueError):
        generate_document_id("x", year=year)


# --- compose(): YEAR source, determinism, override precedence ------------


def _compose_id(meta: SourceMeta, overrides: dict | None = None) -> str:
    out = compose("# Title\n\nbody.\n", meta, PipelineOptions(auto_id=True), overrides)
    return _frontmatter(out)["document_id"]


def test_compose_year_follows_document_date():
    assert _compose_id(_meta(date="2019-03-04")).startswith("LOCAL-2019-DOC-")


def test_compose_year_ignores_frozen_today(monkeypatch):
    _freeze_today(monkeypatch, 2030)
    first = _compose_id(_meta())
    _freeze_today(monkeypatch, 2031)
    second = _compose_id(_meta())
    assert first == second
    assert first.split("-")[1] == "2024"


def test_compose_year_follows_date_override():
    doc_id = _compose_id(_meta(date="2024-06-01"), {"date": "2011-12-31"})
    assert doc_id.split("-")[1] == "2011"


def test_compose_year_from_toml_date_override():
    doc_id = _compose_id(_meta(), {"date": date(2008, 5, 6)})
    assert doc_id.split("-")[1] == "2008"


def test_compose_year_without_source_date_uses_emitted_today(monkeypatch):
    """No source date: the emitted date falls back to today, and so does YEAR."""
    _freeze_today(monkeypatch, 2033)
    out = compose("# T\n\nb\n", _meta(date=None), PipelineOptions(auto_id=True))
    fm = _frontmatter(out)
    assert fm["date"] == "2033-01-02"
    assert fm["document_id"].split("-")[1] == "2033"


def test_compose_explicit_document_id_override_wins():
    assert _compose_id(_meta(), {"document_id": "my-own-id"}) == "my-own-id"


@pytest.mark.parametrize(
    "bad", ["March 2024", "24-01-01", "", ["2024"], True, 99999, 24, 999]
)
def test_compose_unparseable_date_raises(bad):
    with pytest.raises(ValueError, match="date"):
        _compose_id(_meta(), {"date": bad})


def test_compose_unparseable_date_ignored_without_auto_id():
    out = compose("# T\n\nb\n", _meta(), PipelineOptions(), {"date": "March 2024"})
    assert _frontmatter(out)["document_id"] == ""


def test_compose_known_vector_end_to_end():
    opts = PipelineOptions(auto_id=True, auto_id_prefix="CSA", auto_id_type_code="GD")
    out = compose("# Title\n\nbody.\n", _meta(date="2025-02-03"), opts)
    assert _frontmatter(out)["document_id"] == "CSA-2025-GD-0422528348"


def test_auto_id_uses_config_prefix(tmp_path, monkeypatch):
    """``.any2md.toml`` ``[document_id]`` settings drive --auto-id."""
    cfg = tmp_path / ".any2md.toml"
    cfg.write_text('[document_id]\npublisher_prefix = "CSA"\ntype_code = "GD"\n')
    monkeypatch.chdir(tmp_path)
    from any2md.config import (
        discover_config,
        extract_document_id_settings,
        load_toml,
    )

    discovered = discover_config()
    assert discovered == cfg
    p, t = extract_document_id_settings(load_toml(discovered))
    assert p == "CSA"
    assert t == "GD"


def test_year_is_keyword_only():
    """A 1.2.x positional call (body, prefix, type_code) fails loudly."""
    with pytest.raises(TypeError):
        generate_document_id("x", "CSA", "GD")


def test_precomputed_content_hash_gives_same_id():
    body = "# Title\n\nbody.\n"
    h = compute_content_hash(body)
    assert generate_document_id(body, year=2025, content_hash=h) == (
        generate_document_id(body, year=2025)
    )


@pytest.mark.parametrize(
    ("value", "year"),
    [
        ("\n    2025-03-01", 2025),  # unstripped DOCX dcterms:modified
        ("\u0662\u0660\u0662\u0665-01-01", 2025),  # non-ASCII digits via isdigit()
        (2025, 2025),  # TOML integer
        ("2025", 2025),
    ],
)
def test_compose_reads_year_from_extractor_and_toml_dates(value, year):
    assert _compose_id(_meta(), {"date": value}).split("-")[1] == str(year)


def test_compose_empty_document_id_override_does_not_suppress_auto_id():
    doc_id = _compose_id(_meta(), {"document_id": ""})
    assert SAGE_ID_RE.match(doc_id), doc_id


def test_library_error_names_the_option_not_only_the_toml_table():
    opts = PipelineOptions(auto_id=True, auto_id_prefix="csa")
    with pytest.raises(ValueError, match="auto_id_prefix"):
        compose("# T\n\nb\n", _meta(), opts)


@pytest.mark.parametrize("blank", [" ", "\t", [], None])
def test_compose_blank_document_id_override_does_not_suppress_auto_id(blank):
    doc_id = _compose_id(_meta(), {"document_id": blank})
    assert SAGE_ID_RE.match(doc_id), doc_id


@pytest.mark.parametrize("bad_hash", ["-1234567abc", "12", "G" * 64, "A" * 64])
def test_generate_rejects_malformed_content_hash(bad_hash):
    with pytest.raises(ValueError, match="content_hash"):
        generate_document_id("x", year=2025, content_hash=bad_hash)


def test_same_body_different_date_years_get_different_ids():
    """IDs are shared only by the same content_hash and the same date year."""
    a = _compose_id(_meta(date="2025-01-01"))
    b = _compose_id(_meta(date="2026-01-01"))
    assert a.rsplit("-", 1)[1] == b.rsplit("-", 1)[1]
    assert a != b
