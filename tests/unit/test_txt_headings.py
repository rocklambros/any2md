"""TXT structurizer heading levels: one H1 per document, sensible nesting."""

from __future__ import annotations

import re

import pytest

from any2md import pipeline
from any2md.converters.txt import structurize
from any2md.pipeline import PipelineOptions


def _headings(md: str) -> list[str]:
    return re.findall(r"^#{1,6} .*$", md, re.MULTILINE)


def test_title_case_first_line_demotes_equals_underlined_heading():
    md = structurize("My Project\n\nInstallation\n============\n\nRun it.\n")
    assert _headings(md) == ["# My Project", "## Installation"]


def test_title_line_then_both_underline_kinds_nest():
    text = (
        "My Project\n\nOverview\n--------\n\nText.\n\n"
        "Installation\n============\n\nSteps\n-----\n\nRun it.\n"
    )
    assert _headings(structurize(text)) == [
        "# My Project",
        "## Overview",
        "## Installation",
        "### Steps",
    ]


def test_equals_underlined_heading_first_is_the_only_h1():
    text = "Guide\n=====\n\nIntro.\n\nUsage\n=====\n\nDetail\n------\n\nMore.\n"
    assert _headings(structurize(text)) == ["# Guide", "## Usage", "### Detail"]


def test_dash_heading_under_equals_title_is_h2():
    text = "Guide\n=====\n\nIntro.\n\nDetail\n------\n\nMore.\n"
    assert _headings(structurize(text)) == ["# Guide", "## Detail"]


def test_all_caps_after_equals_title_is_h2():
    text = "Guide\n=====\n\nIntro.\n\nSECTION ONE\n\nBody.\n"
    assert _headings(structurize(text)) == ["# Guide", "## Section One"]


def test_single_equals_heading_stays_h1():
    md = structurize("Intro text.\n\nGuide\n=====\n\nBody.\n")
    assert _headings(md) == ["# Guide"]


@pytest.mark.parametrize(
    "text",
    [
        "My Project\n\nInstallation\n============\n\nRun it.\n",
        "Guide\n=====\n\nIntro.\n\nUsage\n=====\n\nMore.\n",
    ],
)
def test_text_lane_reports_no_h1_count_warning(text):
    _, warnings = pipeline.run(structurize(text), "text", PipelineOptions())
    assert not [w for w in warnings if "H1 count" in w]
