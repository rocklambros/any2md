"""Shared cleanup stages leave fenced code blocks unchanged.

C1 (NFC), C2 (soft hyphens), and C3 (ligatures and NBSP) still apply
inside fences on purpose. See the cleanup module docstrings for why.
"""

import random
import re

import pytest

from any2md import pipeline
from any2md.pipeline import PipelineOptions
from any2md.pipeline import cleanup as c

_CODE = "```\nx  =  1   \n\n\n\ny = '\u201cq\u201d \u2026'\n```"


def test_c5_leaves_fenced_whitespace_alone():
    text = "Prose  with   runs.   \n\n\n\n" + _CODE + "\n\n\n\nMore   prose.\n"
    out = c.collapse_whitespace(text, PipelineOptions())
    assert _CODE in out
    assert out.startswith("Prose with runs.\n\n```")
    assert out.endswith("```\n\nMore prose.\n")


@pytest.mark.parametrize(
    "text",
    [
        "a\n\n\n",
        "\n\n\na",
        "\n\n\n\n",
        "a  b \t\n\n\n\nc",
        "x\n```\ncode\n```\n\n\n\n\ny\n",
        "```\ncode\n```\n\n\n",
        "\n\n\n```\ncode\n```",
    ],
)
def test_c5_prose_matches_the_unfenced_algorithm(text):
    # Outside fences C5 must keep its v1.2.1 output exactly, including
    # how blank runs at the start and end of the text are capped.
    assert c.collapse_whitespace(text, PipelineOptions()) == _legacy_c5(text)


def _legacy_c5(s: str) -> str:
    s = c._INTERWORD_RUNS_RE.sub(" ", s)
    s = "\n".join(line.rstrip(" \t") for line in s.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", s)


def test_c5_random_prose_matches_the_unfenced_algorithm():
    rng = random.Random(1210)
    pieces = ["a", "b", " ", "  ", "\t", "\n", "\n\n", "\r", "\f"]
    for _ in range(2000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randrange(12)))
        assert c.collapse_whitespace(text, PipelineOptions()) == _legacy_c5(text)


def test_c4_leaves_fenced_quotes_and_ellipsis_alone():
    text = "\u201cprose\u201d \u2026\n\n" + _CODE + "\n"
    out = c.normalize_quotes_dashes(text, PipelineOptions())
    assert out.startswith('"prose" ...\n\n')
    assert _CODE in out


def test_c8_skips_tilde_fence():
    text = "~~~\nif a &lt; b &amp;&amp; c:\n~~~\n\nA &amp; B\n"
    out = c.decode_html_entities(text, PipelineOptions())
    assert out == "~~~\nif a &lt; b &amp;&amp; c:\n~~~\n\nA & B\n"


def test_c9_skips_tilde_fence():
    text = "~~~\n[x](http://a.example)\n~~~\n\n[y](http://b.example)\n"
    out = c.strip_links(text, PipelineOptions(strip_links=True))
    assert out == "~~~\n[x](http://a.example)\n~~~\n\ny\n"


def test_c6_leaves_fenced_markers_alone():
    text = (
        "Body[^1] text\u00b2.\n\n```\nx = a[^1] + b\u00b2\n```\n\n## Notes\n\n[^1]: n\n"
    )
    out = c.strip_footnote_markers(text, PipelineOptions())
    assert out.startswith("Body text.\n\n```\nx = a[^1] + b\u00b2\n```\n")


def test_c6_ignores_notes_heading_inside_fence():
    text = "Body[^1].\n\n```\n## Notes\n```\n"
    out = c.strip_footnote_markers(text, PipelineOptions())
    assert out == text


def test_c7_ignores_headings_inside_fence():
    text = "# Title\n\n```\n# comment\n#### deep\n```\n\n## Section\n"
    _, warnings = pipeline.run(text, "structured", PipelineOptions())
    assert not [w for w in warnings if w.startswith("validator:")]


def test_c3_still_expands_ligatures_inside_fence():
    # Presentation-form ligatures are PDF extraction artifacts and make
    # an identifier invalid, so C3 repairs them in code too.
    text = "```\nde\ufb01ne()\n```\n"
    assert c.normalize_ligatures(text, PipelineOptions()) == "```\ndefine()\n```\n"
