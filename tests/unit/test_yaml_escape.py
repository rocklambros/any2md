"""Every string the frontmatter emitter writes must round-trip through YAML.

Strings reach the emitter from untrusted places: document metadata (titles,
authors, dates) and discovered ``.any2md.toml`` files. A raw control
character makes the frontmatter invalid YAML, and a raw NEL, LS, or PS is
folded to a space when read back. Each must be escaped.
"""

from __future__ import annotations

import pytest
import yaml

from any2md.frontmatter import _emit_value, compose
from any2md.pipeline import PipelineOptions

from tests.unit.test_auto_id import _frontmatter, _meta

_HOSTILE = (
    [chr(c) for c in range(0x00, 0x20)]
    + [chr(0x7F)]
    + [chr(c) for c in range(0x80, 0xA0)]
    + ["\u2028", "\u2029", "\ufeff", "\ufffe", "\uffff"]
)


@pytest.mark.parametrize("ch", _HOSTILE, ids=lambda c: f"U+{ord(c):04X}")
def test_control_and_separator_characters_round_trip(ch):
    value = f"a{ch}b"
    assert yaml.safe_load(f"k: {_emit_value(value)}")["k"] == value


@pytest.mark.parametrize(
    "value",
    ['quote " and back\\slash', "tab\there", "émoji 🎉 中文", "", "  padded  "],
)
def test_ordinary_text_round_trips(value):
    assert yaml.safe_load(f"k: {_emit_value(value)}")["k"] == value


def test_hostile_title_override_keeps_frontmatter_valid():
    title = "Report\f\x1b[31m\u0085\u2028end"
    out = compose("# T\n\nb\n", _meta(), PipelineOptions(), {"title": title})
    assert _frontmatter(out)["title"] == title
