"""The block scanner helpers accept a line list as well as a string.

In v1.2.1 ``fenced_lines`` and ``protected_lines`` took ``list[str]``.
A list now passes through ``"\\n".join`` before the cached scan, so an
older caller gets the same answer instead of ``TypeError: unhashable
type: 'list'``.
"""

import pytest

from any2md.pipeline.blocks import fenced_lines, find_headings, protected_lines

TEXT = "# Title\n\n```\n# not a heading\n```\n\n> # quoted\n\nSub\n---\n\nBody.\n"


@pytest.mark.parametrize("helper", [fenced_lines, protected_lines, find_headings])
def test_list_and_string_forms_agree(helper):
    assert helper(TEXT.split("\n")) == helper(TEXT)


@pytest.mark.parametrize("helper", [fenced_lines, protected_lines, find_headings])
def test_tuple_form_agrees(helper):
    assert helper(tuple(TEXT.split("\n"))) == helper(TEXT)
