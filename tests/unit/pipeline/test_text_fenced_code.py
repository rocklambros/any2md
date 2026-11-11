"""Text-lane stages leave fenced code blocks unchanged.

Each case is input a stage used to rewrite or drop lines from, with the
affected lines inside a fence. The stage must return it unchanged.
"""

import pytest

from any2md.pipeline import PipelineOptions
from any2md.pipeline import text as t

_TOC_HEADINGS = "".join(f"## Item {k}\n\n" for k in range(6))

CASES = {
    "T1 repair_line_wraps, tilde fence": (
        t.repair_line_wraps,
        "~~~\nfoo(a,\nbar)\n~~~\n",
    ),
    "T2 dehyphenate, tilde fence": (
        t.dehyphenate,
        "~~~\nx = a-\nb\n~~~\n\nab\n",
    ),
    "T9 strip_repeated_byline": (
        t.strip_repeated_byline,
        "```\nContact: a@b.io\nAuthor's Contact Information: x\n```\n",
    ),
    "T3 dedupe_paragraphs": (
        t.dedupe_paragraphs,
        "```\nstart\n\nx = 1\n\nx = 1\n\n\nend\n```\n",
    ),
    "T4 dedupe_toc_block": (
        t.dedupe_toc_block,
        "```toc 1\n"
        + "".join(f"Item {k} {k}\n" for k in range(6))
        + "```\n\n"
        + _TOC_HEADINGS,
    ),
    "T7 dedupe_toc_table": (
        t.dedupe_toc_table,
        "```\n| A | B |\n|---|---|\n| Intro | 1 |\n| Scope | 2 |\n"
        "| Terms | 3 |\n| Usage | 4 |\n```\n\n"
        "## Intro\n\n## Scope\n\n## Terms\n\n## Usage\n\n" + "Text.\n" * 30,
    ),
    "T5 strip_running_headers_footers": (
        t.strip_running_headers_footers,
        "Head\n```\nHead\n1\n```\nbody\n\fHead\n2\nbody\n\fHead\n3\nbody\n",
    ),
    "T10 strip_web_fragments": (
        t.strip_web_fragments,
        "```\nrun();\n\nx = 1\n\ny\n```\n",
    ),
    "strip_orphan_punctuation": (
        t.strip_orphan_punctuation,
        "```\n|\n>\n```\n",
    ),
    "T6 restore_lists_and_code, tilde fence": (
        t.restore_lists_and_code,
        "~~~\n\n    a\n    b\n    c\n    d\n~~~\n",
    ),
    "T8 strip_cover_artifacts": (
        t.strip_cover_artifacts,
        "```\necho 'scan the QR code'\nThird edition 2022-02\n```\n",
    ),
}


def _fenced_part(text: str) -> str:
    """The text between the first opening fence and its closer."""
    lines = text.split("\n")
    opener = next(k for k, ln in enumerate(lines) if ln.startswith(("```", "~~~")))
    marker = lines[opener][:3]
    closer = next(
        k for k in range(opener + 1, len(lines)) if lines[k].startswith(marker)
    )
    return "\n".join(lines[opener : closer + 1])


@pytest.mark.parametrize("name", sorted(CASES))
def test_stage_leaves_fenced_code_alone(name):
    stage, text = CASES[name]
    out = stage(text, PipelineOptions(profile="aggressive"))
    assert _fenced_part(text) in out


def test_t5_still_strips_repeated_header_outside_fence():
    text = "Head\n```\nHead\n```\none\n\fHead\ntwo\n\fHead\nthree"
    out = t.strip_running_headers_footers(text, PipelineOptions())
    assert out == "```\nHead\n```\none\n\ftwo\n\fthree"


def test_t10_still_drops_fragment_after_fence_and_sentence():
    text = "```\ncode\n```\n\nA full sentence.\n\nfragment text\n\nMore prose.\n"
    out = t.strip_web_fragments(text, PipelineOptions())
    assert "fragment text" not in out
    assert "```\ncode\n```" in out


def test_t3_still_dedupes_prose_around_a_fence():
    text = "Same.\n\nSame.\n\n```\nSame.\n\nSame.\n```\n"
    out = t.dedupe_paragraphs(text, PipelineOptions())
    assert out == "Same.\n\n```\nSame.\n\nSame.\n```\n"


def test_t4_ignores_headings_inside_fence():
    toc = "".join(f"Item {k} {k}\n" for k in range(6))
    body = "\n```\n" + "".join(f"## Item {k}\n" for k in range(6)) + "```\n"
    text = toc + body
    assert t.dedupe_toc_block(text, PipelineOptions()) == text


def test_t7_ignores_headings_inside_fence():
    table = (
        "| A | B |\n|---|---|\n| Intro | 1 |\n| Scope | 2 |\n"
        "| Terms | 3 |\n| Usage | 4 |\n"
    )
    body = "\n```\n## Intro\n## Scope\n## Terms\n## Usage\n```\n" + "Text.\n" * 30
    text = table + body
    assert t.dedupe_toc_table(text, PipelineOptions()) == text
