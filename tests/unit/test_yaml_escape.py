"""Every string the frontmatter emitter writes must round-trip through YAML.

Strings reach the emitter from untrusted places: document metadata (titles,
authors, dates) and discovered ``.any2md.toml`` files. A raw control
character makes the frontmatter invalid YAML, and a raw NEL, LS, or PS is
folded to a space when read back. Each must be escaped.
"""

from __future__ import annotations

import pytest
import yaml

from any2md.frontmatter import FrontmatterEmitError, _emit_value, compose
from any2md.pipeline import PipelineOptions

from tests.unit.test_auto_id import _frontmatter, _meta

_HOSTILE = (
    [chr(c) for c in range(0x00, 0x20)]
    + [chr(0x7F)]
    + [chr(c) for c in range(0x80, 0xA0)]
    + ["\u2028", "\u2029", "\ufeff", "\ufffe", "\uffff"]
)


# libyaml (CSafeLoader) is what most consumers use, and it is stricter than
# pure-Python PyYAML, so every round trip is checked under both.
_LOADERS = [yaml.SafeLoader] + ([yaml.CSafeLoader] if yaml.__with_libyaml__ else [])


def _load(text, loader):
    return yaml.load(text, Loader=loader)


@pytest.mark.parametrize("loader", _LOADERS, ids=lambda c: c.__name__)
@pytest.mark.parametrize("ch", _HOSTILE, ids=lambda c: f"U+{ord(c):04X}")
def test_control_and_separator_characters_round_trip(ch, loader):
    value = f"a{ch}b"
    assert _load(f"k: {_emit_value(value)}", loader)["k"] == value


@pytest.mark.parametrize("ch", ["\udcff", "\ud800", "\udfff"])
def test_lone_surrogate_fails_the_file_instead_of_emitting(ch):
    """Undecodable argv bytes arrive as lone surrogates. UTF-8 cannot hold one."""
    with pytest.raises(FrontmatterEmitError, match="surrogate"):
        _emit_value(f"a{ch}b")


@pytest.mark.parametrize(
    "value",
    ['quote " and back\\slash', "tab\there", "émoji 🎉 中文", "", "  padded  "],
)
@pytest.mark.parametrize("loader", _LOADERS, ids=lambda c: c.__name__)
def test_ordinary_text_round_trips(value, loader):
    assert _load(f"k: {_emit_value(value)}", loader)["k"] == value


def test_hostile_title_override_keeps_frontmatter_valid():
    title = "Report\f\x1b[31m\u0085\u2028end"
    out = compose("# T\n\nb\n", _meta(), PipelineOptions(), {"title": title})
    assert _frontmatter(out)["title"] == title


_KEYWORD_KEYS = ["yes", "No", "ON", "off", "True", "false", "null", "NULL", "y", "n"]


@pytest.mark.parametrize("loader", _LOADERS, ids=lambda c: c.__name__)
def test_yaml_keyword_keys_load_back_as_strings(loader):
    overrides = {k: f"v-{k}" for k in _KEYWORD_KEYS}
    out = compose("# T\n\nb\n", _meta(), PipelineOptions(), overrides)
    end = out.index("\n---\n", 4)
    fm = _load(out[4:end], loader)
    for k in _KEYWORD_KEYS:
        assert fm[k] == f"v-{k}"


def test_ordinary_keys_stay_plain():
    out = compose("# T\n\nb\n", _meta(), PipelineOptions(), {"tlp": "x"})
    assert "\ntlp: " in out
    assert "\ntitle: " in out


@pytest.mark.parametrize("loader", _LOADERS, ids=lambda c: c.__name__)
@pytest.mark.parametrize(
    "value", [float("inf"), float("-inf"), 1e20, 1e-7, 0.5, -2.0, 1.5e300]
)
def test_floats_round_trip_as_floats(value, loader):
    loaded = _load(f"k: {_emit_value(value)}", loader)["k"]
    assert isinstance(loaded, float)
    assert loaded == value


@pytest.mark.parametrize("loader", _LOADERS, ids=lambda c: c.__name__)
def test_nan_round_trips_as_nan(loader):
    loaded = _load(f"k: {_emit_value(float('nan'))}", loader)["k"]
    assert isinstance(loaded, float)
    assert loaded != loaded
