"""Regression tests for super-linear regex and loop behavior on untrusted text.

Every converted document is attacker-controlled input. Each test feeds a
payload that made a stage backtrack in quadratic, cubic, or exponential
time before v1.2.1 and asserts it now finishes inside a small CPU budget.
Payload sizes are chosen so the vulnerable code needs minutes and the
linear code needs milliseconds, which keeps the budget far from flaky.

POSIX only: the budget uses SIGALRM, which also interrupts a running
``re`` match.
"""

from __future__ import annotations

import signal
import sys
from contextlib import contextmanager

import pytest

from any2md import heuristics
from any2md.converters.txt import structurize
from any2md.frontmatter import derive_title
from any2md.pipeline import PipelineOptions
from any2md.pipeline import cleanup, structured, text

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="SIGALRM is POSIX-only")

BUDGET_S = 2.0
AGGR = PipelineOptions(profile="aggressive")


@contextmanager
def _budget(seconds: float = BUDGET_S):
    def _expired(*_args):
        raise TimeoutError(f"exceeded {seconds}s: super-linear behavior")

    previous = signal.signal(signal.SIGALRM, _expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


# ---------- heuristics.py ----------


def test_f1_academic_byline_not_exponential():
    body = "# TITLE\n\n" + "ABC ," * 40 + "ABC x\n"
    with _budget():
        assert heuristics.extract_authors(body, title_hint=None) == []


def test_f13_toc_hint_on_long_dot_run():
    with _budget():
        heuristics._is_skip_paragraph("." * 300_000)


def test_f15_cleanup_abstract_on_unclosed_brackets():
    with _budget():
        heuristics._cleanup_abstract("[" * 300_000)


def test_author_prefix_line_with_huge_whitespace_runs():
    body = "# T\n\nAuthors: " + "a" + " " * 300_000 + "x\n"
    with _budget():
        heuristics.extract_authors(body, title_hint=None)


# ---------- frontmatter.py ----------


def test_f2_derive_title_whitespace_run_in_h1():
    # U+3000 (ideographic space) survives NFC, C3, and the ASCII-only C5.
    body = "# A" + "\u3000" * 300_000 + "B\n"
    with _budget():
        assert derive_title(body, None, "x.txt").startswith("A")


# ---------- pipeline/text.py ----------


def test_f3_f5_toc_line_cubic():
    body = "a" + " " * 5_000 + "b\n\nBody.\n"
    with _budget():
        text.dedupe_toc_block(body, AGGR)


def test_f18_body_heading_whitespace_run():
    toc = "".join(f"Entry {i} {i}\n" for i in range(1, 6))
    body = toc + "Ordinary sentence.\n## a" + " " * 300_000 + "b\n"
    with _budget():
        text.dedupe_toc_block(body, AGGR)


def test_f17_f20_contact_line_many_at_signs():
    body = "Contact:" + "@" * 300_000 + "\n"
    with _budget():
        text.strip_repeated_byline(body, AGGR)


# ---------- pipeline/cleanup.py ----------


def test_f4_f21_trailing_whitespace_run():
    body = " " * 300_000 + "x\n"
    with _budget():
        assert cleanup.collapse_whitespace(body, AGGR).endswith("x\n")


def test_f19_strip_links_unclosed_brackets():
    body = "[" * 300_000 + "](\n"
    with _budget():
        cleanup.strip_links(body, PipelineOptions(strip_links=True))


# ---------- pipeline/structured.py (found while auditing the same shapes) ----------


def test_s4_heading_whitespace_run():
    body = "# a" + " " * 300_000 + "b\n"
    with _budget():
        structured.enforce_heading_hierarchy(body, AGGR)


def test_s1_image_link_unclosed_brackets():
    body = "![" * 150_000 + "\n"
    with _budget():
        structured.lift_figure_captions(body, AGGR)


def test_s1_unclosed_figure_tags():
    body = "<figure>" * 50_000 + "<figcaption>x</figcaption>\n"
    with _budget():
        structured.lift_figure_captions(body, AGGR)


# ---------- converters/txt.py ----------


def test_f10_structurize_long_blank_run_in_indented_block():
    body = "    a\n" + "\n" * 50_000 + "    b\n"
    with _budget():
        out = structurize(body)
    assert "a" in out and "b" in out


def test_picture_line_check_is_linear():
    # A long alt text full of escapes, and a long destination with no
    # closing parenthesis, both fail in one pass.
    with _budget():
        assert not text._is_picture_line("![" + "\\]" * 200_000)
        assert not text._is_picture_line("[![a](" + "b" * 200_000)
        assert not text._is_picture_line("[![" + "a" * 200_000 + "](b)](c")
