"""Tests for C9 — strip_links (--strip-links / --profile maximum).

Before v1.2.1 the flag was parsed into PipelineOptions but no stage read
it, so links always survived.
"""

import pytest

from any2md.pipeline import PipelineOptions, run
from any2md.pipeline.cleanup import STAGES, strip_links

ON = PipelineOptions(strip_links=True)
OFF = PipelineOptions(strip_links=False)


def test_strips_inline_link_to_text():
    assert strip_links("See [the docs](https://x.io/a) now.", ON) == "See the docs now."


def test_off_by_default_is_noop():
    text = "See [the docs](https://x.io/a) now."
    assert strip_links(text, OFF) == text
    assert PipelineOptions().strip_links is False


def test_keeps_images():
    text = "![diagram](img/a.png) and [link](https://x.io)"
    assert strip_links(text, ON) == "![diagram](img/a.png) and link"


def test_url_with_balanced_parentheses():
    text = "[Python](https://en.wikipedia.org/wiki/Python_(language)) rocks"
    assert strip_links(text, ON) == "Python rocks"


def test_link_with_title():
    assert strip_links('[a](https://x.io "Title") b', ON) == "a b"


def test_multiple_links_on_one_line():
    text = "[a](u1), [b](u2) and [c](u3)."
    assert strip_links(text, ON) == "a, b and c."


def test_empty_link_text_removed():
    assert strip_links("x [](https://x.io) y", ON) == "x  y"


def test_fenced_code_untouched():
    text = "```\n[a](https://x.io)\n```\n[b](https://y.io)"
    assert strip_links(text, ON) == "```\n[a](https://x.io)\n```\nb"


def test_inline_code_untouched():
    text = "Use `[a](b)` syntax; see [docs](https://x.io)."
    assert strip_links(text, ON) == "Use `[a](b)` syntax; see docs."


def test_registered_in_shared_cleanup_before_validate():
    names = [s.__name__ for s in STAGES]
    assert "strip_links" in names
    assert names.index("strip_links") < names.index("validate")


@pytest.mark.parametrize("lane", ["text", "structured"])
def test_runs_in_both_lanes(lane):
    out, _ = run("# T\n\nSee [docs](https://x.io).\n", lane, ON)
    assert "https://x.io" not in out
    assert "See docs." in out
