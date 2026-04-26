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


# --------------------------------------------------------------------- #
# refine_title
# --------------------------------------------------------------------- #


class TestRefineTitle:
    def test_clean_h1_returned_unchanged(self):
        result = heuristics.refine_title(
            "AI Governance through Markets",
            "# AI Governance through Markets\n\nBody content here...",
        )
        assert result == "AI Governance through Markets"

    def test_international_standard_replaced_by_next_h2(self):
        body = (
            "# INTERNATIONAL STANDARD\n\n"
            "Some boilerplate.\n\n"
            "## Information security, cybersecurity and privacy protection\n\n"
            "Body...\n"
        )
        result = heuristics.refine_title("INTERNATIONAL STANDARD", body)
        assert result == (
            "Information security, cybersecurity and privacy protection"
        )

    def test_technical_report_replaced_by_next_h2(self):
        body = (
            "# TECHNICAL REPORT\n\n"
            "Cover boilerplate.\n\n"
            "## Real Title Here\n\nBody...\n"
        )
        result = heuristics.refine_title("TECHNICAL REPORT", body)
        assert result == "Real Title Here"

    def test_wikipedia_namespace_prefix_stripped(self):
        result = heuristics.refine_title(
            "Wikipedia:Signs of AI writing",
            "# Wikipedia:Signs of AI writing\n\nBody...\n",
            source_url="https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing",
        )
        assert result == "Signs of AI writing"

    def test_docx_line_break_aggressive_splits_on_explicit_delimiter(self):
        # Best-effort heuristic: only split when there's an explicit
        # delimiter such as " - " or "Final Project ". This is documented
        # as conservative-by-design even at aggressive profile.
        candidate = "COMP 4441 Final Project Safety Alignment Effectiveness in LLMs"
        result_aggressive = heuristics.refine_title(
            candidate, "# " + candidate + "\n\nBody...\n",
            profile="aggressive",
        )
        # Aggressive profile: split at "Final Project " delimiter.
        assert result_aggressive == "Safety Alignment Effectiveness in LLMs"

        # Conservative profile: leave untouched.
        result_conservative = heuristics.refine_title(
            candidate, "# " + candidate + "\n\nBody...\n",
            profile="conservative",
        )
        assert result_conservative == candidate

    def test_conservative_profile_skips_wikipedia_and_docx_refinements(self):
        # Conservative still applies cover-page-boilerplate skip-list.
        body = "# INTERNATIONAL STANDARD\n\n## Real Title\n\nBody..."
        result = heuristics.refine_title(
            "INTERNATIONAL STANDARD", body, profile="conservative",
        )
        assert result == "Real Title"

        # But conservative does NOT strip Wikipedia namespace prefix.
        result_wiki = heuristics.refine_title(
            "Wikipedia:Signs of AI writing",
            "# Wikipedia:Signs of AI writing\n\nBody...\n",
            source_url="https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing",
            profile="conservative",
        )
        assert result_wiki == "Wikipedia:Signs of AI writing"
