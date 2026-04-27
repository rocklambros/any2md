"""Tests for C3 — normalize_ligatures."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.cleanup import normalize_ligatures


def test_normalize_ligatures_fi():
    assert normalize_ligatures("ﬁne", PipelineOptions()) == "fine"


def test_normalize_ligatures_fl():
    assert normalize_ligatures("ﬂow", PipelineOptions()) == "flow"


def test_normalize_ligatures_ffi_ffl():
    assert (
        normalize_ligatures("ﬃlation ﬄuent", PipelineOptions()) == "ffilation ffluent"
    )


def test_normalize_ligatures_nbsp_to_space():
    assert normalize_ligatures("foo bar", PipelineOptions()) == "foo bar"


def test_normalize_ligatures_preserves_superscripts():
    # NFKC would fold superscript-2 to "2" — we deliberately do not.
    text = "x² + y²"
    assert normalize_ligatures(text, PipelineOptions()) == text


def test_normalize_ligatures_noop_on_clean_text():
    text = "clean ascii text"
    assert normalize_ligatures(text, PipelineOptions()) == text
