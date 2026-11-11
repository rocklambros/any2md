"""Unit tests for ``frontmatter.compose(overrides=...)``.

The ``overrides`` arg lets callers (CLI ``--meta`` / ``--meta-file`` /
``.any2md.toml``) deep-merge user-supplied values into the derived field
map *after* derivation but *before* YAML emission. Overrides win over
derived values; nested dicts merge recursively; lists/scalars replace.
"""

from __future__ import annotations

import tomllib

import pytest
import yaml

from any2md.frontmatter import SourceMeta, compose
from any2md.pipeline import PipelineOptions


def _meta(**kw):
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
    base.update(kw)
    return SourceMeta(**base)


def _fm(text: str) -> dict:
    """Parse the YAML frontmatter block from a composed document."""
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end])


def test_simple_override():
    out = compose(
        "# T\n\nbody\n",
        _meta(),
        PipelineOptions(),
        overrides={"organization": "OWASP"},
    )
    assert _fm(out)["organization"] == "OWASP"


def test_array_override():
    out = compose(
        "# T\n\nbody\n",
        _meta(),
        PipelineOptions(),
        overrides={"authors": ["Alice", "Bob"]},
    )
    assert _fm(out)["authors"] == ["Alice", "Bob"]


def test_nested_override():
    out = compose(
        "# T\n\nbody\n",
        _meta(),
        PipelineOptions(),
        overrides={"generation_metadata": {"authored_by": "human"}},
    )
    fm = _fm(out)
    assert fm["generation_metadata"]["authored_by"] == "human"


def test_override_wins_over_derived():
    # title would normally come from H1
    out = compose(
        "# Auto\n\nbody\n",
        _meta(),
        PipelineOptions(),
        overrides={"title": "Manual"},
    )
    assert _fm(out)["title"] == "Manual"


def test_nested_list_override_renders_as_flow_list():
    # Mirrors ``--meta review.approvers=x,y``: the parser yields a list
    # under a nested key, which must render like a top-level list.
    out = compose(
        "# T\n\nbody\n",
        _meta(),
        PipelineOptions(),
        overrides={"review": {"approvers": ["x", "y"]}},
    )
    assert '\n  approvers: ["x", "y"]\n' in out
    assert _fm(out)["review"] == {"approvers": ["x", "y"]}


def test_list_inside_doubly_nested_dict():
    out = compose(
        "# T\n\nbody\n",
        _meta(),
        PipelineOptions(),
        overrides={"a": {"b": {"c": ["x", "y"], "d": "z"}}},
    )
    assert _fm(out)["a"] == {"b": {"c": ["x", "y"], "d": "z"}}


def test_empty_nested_table_stays_a_mapping():
    # A TOML ``[meta.review.details]`` table with no keys parses to {}.
    out = compose(
        "# T\n\nbody\n",
        _meta(),
        PipelineOptions(),
        overrides={"review": {"details": {}}},
    )
    assert "\n  details: {}\n" in out
    assert _fm(out)["review"] == {"details": {}}


def test_empty_top_level_table_stays_a_mapping():
    out = compose(
        "# T\n\nbody\n",
        _meta(),
        PipelineOptions(),
        overrides={"review": {}},
    )
    assert "\nreview: {}\n" in out
    assert _fm(out)["review"] == {}


def test_unsupported_value_raises_value_error():
    # Converters report ValueError as a per-file failure, so an emission
    # error must surface as one rather than escape as a TypeError.
    with pytest.raises(ValueError, match="unsupported"):
        compose(
            "# T\n\nbody\n",
            _meta(),
            PipelineOptions(),
            overrides={"a": {"b": object()}},
        )


def _compose_toml(toml_text: str) -> str:
    """Compose with overrides parsed by tomllib, the same path config uses."""
    return compose(
        "# T\n\nbody\n",
        _meta(),
        PipelineOptions(),
        overrides=tomllib.loads(toml_text),
    )


def test_toml_date_emits_quoted_iso_string():
    out = _compose_toml("reviewed = 2026-01-01\n")
    assert '\nreviewed: "2026-01-01"\n' in out
    assert _fm(out)["reviewed"] == "2026-01-01"


def test_toml_offset_datetime_keeps_its_offset():
    out = _compose_toml(
        "published = 1979-05-27T07:32:00Z\nedited = 1979-05-27T00:32:00-07:00\n"
    )
    fm = _fm(out)
    assert fm["published"] == "1979-05-27T07:32:00+00:00"
    assert fm["edited"] == "1979-05-27T00:32:00-07:00"


def test_toml_local_datetime_and_time():
    out = _compose_toml("stamp = 1979-05-27T07:32:00.5\nat = 07:32:00\n")
    fm = _fm(out)
    assert fm["stamp"] == "1979-05-27T07:32:00.500000"
    assert fm["at"] == "07:32:00"


def test_toml_date_inside_nested_table():
    out = _compose_toml(
        "[review]\nwhen = 2026-01-01\n[review.audit]\nat = 2026-02-03\n"
    )
    assert _fm(out)["review"] == {"when": "2026-01-01", "audit": {"at": "2026-02-03"}}


def test_toml_date_list_emits_iso_strings():
    # str() of a datetime uses a space separator, so the list path must
    # format items the same way the scalar path does.
    out = _compose_toml(
        "dates = [2026-01-01, 1979-05-27T07:32:00Z]\n[review]\ndays = [2026-03-04]\n"
    )
    assert '\ndates: ["2026-01-01", "1979-05-27T07:32:00+00:00"]\n' in out
    fm = _fm(out)
    assert fm["dates"] == ["2026-01-01", "1979-05-27T07:32:00+00:00"]
    assert fm["review"] == {"days": ["2026-03-04"]}


def test_toml_date_override_matches_builtin_date_format():
    derived = compose("# T\n\nbody\n", _meta(date="2025-12-31"), PipelineOptions())
    assert '\ndate: "2025-12-31"\n' in derived
    out = _compose_toml("date = 2026-01-01\n")
    assert '\ndate: "2026-01-01"\n' in out


def test_list_of_tables_raises_value_error():
    # ``[[reviewers]]`` parses to a list of dicts. The flow-list emitter
    # has no mapping form, so the file must fail instead of emitting
    # Python repr text inside quotes.
    with pytest.raises(ValueError, match="list item"):
        _compose_toml('[[reviewers]]\nname = "A"\n')


def test_nested_list_raises_value_error():
    with pytest.raises(ValueError, match="list item"):
        _compose_toml("grid = [[1, 2], [3]]\n")
