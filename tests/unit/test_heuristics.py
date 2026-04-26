"""Unit tests for any2md/heuristics.py.

See spec §4 (heuristics module contract) and plan Batch A.
"""

from __future__ import annotations

import pytest

from any2md import heuristics
from any2md.heuristics import OrgFilterResult


# --------------------------------------------------------------------- #
# filter_organization
# --------------------------------------------------------------------- #


class TestFilterOrganization:
    def test_real_org_name_returned_as_organization(self):
        result = heuristics.filter_organization("Acme Research Institute")
        assert result == OrgFilterResult("Acme Research Institute", None)

    def test_latex_acmart_returned_as_produced_by(self):
        value = "LaTeX with acmart 2024/08/25 v2.09 ..."
        result = heuristics.filter_organization(value)
        assert result == OrgFilterResult(None, value)

    def test_adobe_indesign_returned_as_produced_by(self):
        value = "Adobe InDesign 16.2 (Windows)"
        result = heuristics.filter_organization(value)
        assert result == OrgFilterResult(None, value)

    def test_microsoft_word_returned_as_produced_by(self):
        value = "Microsoft® Word for Microsoft 365"
        result = heuristics.filter_organization(value)
        assert result == OrgFilterResult(None, value)

    @pytest.mark.parametrize("inp", [None, "", "   "])
    def test_empty_input_returns_all_none(self, inp):
        result = heuristics.filter_organization(inp)
        assert result == OrgFilterResult(None, None)
