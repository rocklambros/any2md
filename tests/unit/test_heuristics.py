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


# --------------------------------------------------------------------- #
# refine_abstract
# --------------------------------------------------------------------- #


class TestRefineAbstract:
    def test_clean_candidate_returned_unchanged(self):
        candidate = (
            "This paper presents a novel approach to AI alignment. "
            "We demonstrate that markets can effectively govern AI "
            "deployment when proper incentive structures are in place. "
            "Our results show significant improvements over the baseline."
        )
        body = "# Title\n\n" + candidate + "\n\n## Section\n\nContent..."
        result = heuristics.refine_abstract(candidate, body)
        assert result == candidate

    def test_abstract_heading_in_body_preferred_over_candidate(self):
        candidate = (
            "BYLINE Adams Smith, John Doe 1, 2 University Name (some affiliation)"
        )
        real_abstract = (
            "We propose a new framework for AI governance through market "
            "mechanisms. The approach combines economic incentives with "
            "technical safeguards. Empirical evaluation shows that the "
            "framework achieves better outcomes than alternatives."
        )
        body = (
            "# Paper Title\n\n"
            + candidate
            + "\n\n## Abstract\n\n"
            + real_abstract
            + "\n\n## Introduction\n\nIntro text...\n"
        )
        result = heuristics.refine_abstract(candidate, body)
        assert result == real_abstract

    def test_byline_pattern_candidate_skipped(self):
        # Byline candidate matches pattern (caps-heavy + comma + digit).
        # Heuristic walks to next paragraph in body that doesn't match
        # any skip pattern.
        candidate = "PHILIP MOREIRA TOMEI 1, 2, RUPAL JAIN 2, 3"
        next_para = (
            "This paper investigates AI governance frameworks. "
            "We provide a comprehensive analysis of existing market-based "
            "mechanisms and propose new approaches that better align "
            "private and public interests."
        )
        body = (
            "# Paper Title\n\n"
            + candidate
            + "\n\n"
            + next_para
            + "\n\n## Section\n\nContent...\n"
        )
        result = heuristics.refine_abstract(candidate, body)
        assert result == next_para

    def test_qr_code_candidate_skipped(self):
        candidate = (
            "Please share your feedback. Scan the QR code to access "
            "the customer feedback form. Your responses help us improve."
        )
        next_para = (
            "Information security, cybersecurity, and privacy protection "
            "are critical concerns for modern organizations. This standard "
            "provides a comprehensive set of controls and guidance for "
            "implementing an information security management system."
        )
        body = (
            "# ISO Standard\n\n"
            + candidate
            + "\n\n"
            + next_para
            + "\n\n## Body\n\nContent...\n"
        )
        result = heuristics.refine_abstract(candidate, body)
        assert result == next_para

    def test_markdown_links_stripped(self):
        candidate = (
            "This paper discusses [machine learning](https://example.com) "
            "and [neural networks](https://other.example) in the context "
            "of large-scale [deployment](https://yet.another.example). "
            "Our findings have important implications for the field."
        )
        body = "# Title\n\n" + candidate + "\n"
        result = heuristics.refine_abstract(candidate, body)
        assert "[" not in result
        assert "(http" not in result
        assert "machine learning" in result
        assert "neural networks" in result

    def test_html_entities_decoded(self):
        candidate = (
            "This paper presents an analysis of AI &amp; ML governance. "
            "We show that &lt;safety&gt; constraints are essential for "
            "responsible deployment in production environments. The work "
            "extends prior research on alignment techniques."
        )
        body = "# Title\n\n" + candidate + "\n"
        result = heuristics.refine_abstract(candidate, body)
        assert "&amp;" not in result
        assert "&lt;" not in result
        assert "AI & ML" in result
        assert "<safety>" in result

    def test_long_candidate_truncated_at_sentence_boundary(self):
        sentences = [
            "This paper introduces a novel framework for governance.",
            "The framework combines economic and technical mechanisms.",
            "We evaluate the framework across multiple deployment scenarios.",
            "Our results demonstrate significant improvements over baselines.",
            "Future work will explore extensions to broader application areas.",
            "Acknowledgments and references follow this section.",
            "Additional considerations include scalability and robustness.",
            "Several open questions remain for follow-up investigation.",
        ]
        candidate = " ".join(sentences)
        assert len(candidate) > 400
        body = "# Title\n\n" + candidate + "\n"
        result = heuristics.refine_abstract(candidate, body)
        assert len(result) <= 400
        # Last char should be sentence terminator (period, ?, !)
        assert result[-1] in ".?!"

    def test_conservative_profile_returns_none_when_no_clean_candidate(self):
        # Candidate is byline (skipped). No "## Abstract" heading.
        # Body has no acceptable fallback paragraph (only short or
        # skipped content). Conservative profile returns None.
        candidate = "PHILIP MOREIRA TOMEI 1, 2, RUPAL JAIN 2, 3"
        body = (
            "# Title\n\n"
            + candidate
            + "\n\nShort line.\n\n"
            "Page 5\n\n## Section\n\nContent...\n"
        )
        result = heuristics.refine_abstract(
            candidate, body, profile="conservative",
        )
        assert result is None


# --------------------------------------------------------------------- #
# extract_authors
# --------------------------------------------------------------------- #


class TestExtractAuthors:
    def test_authors_prefix_extracted(self):
        body = (
            "# Paper Title\n\n"
            "Authors: Alice, Bob, Carol\n\n"
            "Some body content..."
        )
        result = heuristics.extract_authors(body, title_hint="Paper Title")
        assert result == ["Alice", "Bob", "Carol"]

    def test_by_prefix_extracted(self):
        body = (
            "# Paper Title\n\n"
            "By Jane Doe\n\n"
            "Some body content..."
        )
        result = heuristics.extract_authors(body, title_hint="Paper Title")
        assert result == ["Jane Doe"]

    def test_academic_byline_extracted_aggressive(self):
        body = (
            "# AI Governance through Markets\n\n"
            "PHILIP MOREIRA TOMEI 1, 2, RUPAL JAIN 2, 3\n\n"
            "Some abstract content here..."
        )
        result = heuristics.extract_authors(body, title_hint=None)
        assert result == ["Philip Moreira Tomei", "Rupal Jain"]

    def test_duplicate_authors_deduplicated(self):
        body = (
            "# Paper Title\n\n"
            "Authors: Alice Smith, Bob Jones, alice smith, ALICE SMITH\n\n"
            "Body..."
        )
        result = heuristics.extract_authors(body, title_hint=None)
        # Only one "Alice Smith" should remain (case-insensitive dedup),
        # in original order.
        assert len(result) == 2
        assert result[0].lower() == "alice smith"
        assert result[1].lower() == "bob jones"

    def test_more_than_20_authors_capped(self):
        names = [f"Author{i}" for i in range(30)]
        body = (
            "# Paper\n\n"
            "Authors: " + ", ".join(names) + "\n\nBody..."
        )
        result = heuristics.extract_authors(body, title_hint=None)
        assert len(result) == 20

    def test_conservative_profile_skips_byline_pattern(self):
        # Same body as test_academic_byline_extracted_aggressive but
        # without "Authors:"/"By" prefix. Conservative should NOT use
        # the byline pattern and should return [].
        body = (
            "# AI Governance through Markets\n\n"
            "PHILIP MOREIRA TOMEI 1, 2, RUPAL JAIN 2, 3\n\n"
            "Some abstract content here..."
        )
        result = heuristics.extract_authors(
            body, title_hint=None, profile="conservative",
        )
        assert result == []

    def test_empty_body_returns_empty_list(self):
        result = heuristics.extract_authors("", title_hint=None)
        assert result == []


# --------------------------------------------------------------------- #
# is_arxiv_filename
# --------------------------------------------------------------------- #


class TestIsArxivFilename:
    def test_new_format_with_version_qualifier(self):
        assert heuristics.is_arxiv_filename("2501.17755v1.pdf") == "2501.17755"

    def test_legacy_4digit_format(self):
        assert heuristics.is_arxiv_filename("1706.03762.pdf") == "1706.03762"

    def test_no_version_qualifier(self):
        assert heuristics.is_arxiv_filename("2501.17755.pdf") == "2501.17755"

    def test_non_arxiv_filename_returns_none(self):
        assert heuristics.is_arxiv_filename("report.pdf") is None
