"""Behavior kept intact by the ReDoS rewrites, from review of PR #45.

Each rewrite in ``test_redos_hardening.py`` had to stay linear without
dropping output the old patterns produced. These cases cover the four
regressions review found: abstracts cut through a link, long author
lists rejected, escaped brackets in link labels, and non-ASCII page
numbers in a table of contents. The budget tests at the end keep the
escape-aware patterns linear.
"""

from __future__ import annotations

import sys

import pytest

from any2md import heuristics
from any2md.pipeline import PipelineOptions
from any2md.pipeline import cleanup, structured
from any2md.pipeline.text import _toc_title

from .test_redos_hardening import _budget

AGGR = PipelineOptions(profile="aggressive")
STRIP = PipelineOptions(strip_links=True)


def test_abstract_cleanup_never_leaves_a_cut_link():
    url = "https://example.com/" + "a" * 1900
    para = " ".join(f"[source {i}]({url})" for i in range(5)) + "."
    out = heuristics._cleanup_abstract(para)
    assert "](" not in out and "https://" not in out
    assert out.startswith("source 0 source 1")


def test_labelled_author_list_over_300_chars_is_kept():
    names = [f"Author{chr(65 + i)} Surnamexxxx" for i in range(20)]
    line = "Authors: " + ", ".join(names)
    assert len(line) > 300
    body = "# Title\n\n" + line + "\n\nBody text.\n"
    for profile in ("conservative", "aggressive"):
        got = heuristics.extract_authors(
            body, title_hint=None, arxiv_lookup_enabled=False, profile=profile
        )
        assert got == names, profile


def test_very_long_author_list_keeps_first_twenty():
    names = [f"Person{i:03d} Lastname" for i in range(400)]
    body = "# Title\n\nAuthors: " + ", ".join(names) + "\n"
    got = heuristics.extract_authors(body, title_hint=None, arxiv_lookup_enabled=False)
    assert got == names[:20]


@pytest.mark.skipif(sys.platform == "win32", reason="SIGALRM is POSIX-only")
def test_author_list_whitespace_runs_stay_linear():
    body = "# T\n\nAuthors: Ann" + " " * 200_000 + "x" + "\n"
    with _budget():
        heuristics.extract_authors(body, title_hint=None, arxiv_lookup_enabled=False)


def test_strip_links_keeps_escaped_bracket_label():
    assert cleanup.strip_links("[array\\[i](https://x.io)", STRIP) == "array\\[i"


def test_abstract_link_strip_keeps_escaped_bracket_label():
    assert heuristics._MD_LINK_RE.sub(r"\1\2", "[a\\]b](u)") == "a\\]b"


def test_figure_caption_keeps_escaped_bracket_alt():
    out = structured.lift_figure_captions("![a\\[b](img.png)", AGGR)
    assert out.strip() == "*Figure: a\\[b*"


@pytest.mark.parametrize("page", ["١", "१२", "12"])
def test_toc_title_accepts_unicode_decimal_page_numbers(page):
    assert _toc_title(f"Introduction ..... {page}") == "Introduction"
    assert _toc_title(f"2.1 Methods {page}") == "Methods"


@pytest.mark.skipif(sys.platform == "win32", reason="SIGALRM is POSIX-only")
@pytest.mark.parametrize(
    "payload",
    [
        "\\[" * 150_000,
        "[" + "\\[" * 150_000,
        "[" + "\\" * 150_000,
        "[a\\]" * 100_000,
    ],
)
def test_escape_aware_link_patterns_stay_linear(payload):
    with _budget():
        cleanup.strip_links(payload + "](", STRIP)
        heuristics._MD_LINK_RE.sub(r"\1\2", payload)
        structured.lift_figure_captions("!" + payload, AGGR)


@pytest.mark.skipif(sys.platform == "win32", reason="SIGALRM is POSIX-only")
def test_toc_title_long_decimal_run_stays_linear():
    with _budget():
        _toc_title("Title " + "١" * 200_000)


@pytest.mark.skipif(sys.platform == "win32", reason="SIGALRM is POSIX-only")
def test_byline_at_author_cap_stays_linear():
    # The cap rose from 300 to 4096 characters, so the failing-byline shape
    # from F1 must stay fast at the new length too.
    line = ("ABC ," * 900 + "ABC x")[: heuristics._MAX_AUTHOR_LINE]
    with _budget():
        heuristics.extract_authors("# T\n\n" + line + "\n", title_hint=None)


@pytest.mark.parametrize(
    ("prefix", "linked"),
    [("", True), ("\\", False), ("\\\\", True), ("\\\\\\", False)],
)
def test_link_escape_follows_backslash_parity(prefix, linked):
    # An even backslash run escapes itself, so the "[" after it opens a link.
    # The backslashes stay in the output either way.
    src = prefix + "[docs](https://x.io)"
    want = prefix + "docs" if linked else src
    assert cleanup.strip_links(src, STRIP) == want
    assert heuristics._MD_LINK_RE.sub(r"\1\2", src) == want


@pytest.mark.skipif(sys.platform == "win32", reason="SIGALRM is POSIX-only")
def test_backslash_run_before_bracket_stays_linear():
    for payload in ("\\" * 200_000 + "[", "\\" * 200_001 + "[a]"):
        with _budget():
            cleanup.strip_links(payload + "](", STRIP)
            heuristics._MD_LINK_RE.sub(r"\1\2", payload)
