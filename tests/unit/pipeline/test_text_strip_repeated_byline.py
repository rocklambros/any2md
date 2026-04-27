"""Tests for T9 — strip_repeated_byline."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.text import strip_repeated_byline


def test_drops_authors_contact_information_singular():
    text = (
        "# Title\n"
        "\n"
        "Author's Contact Information: Philip Smith, philip@example.com\n"
        "\n"
        "Body content here.\n"
    )
    out = strip_repeated_byline(text, PipelineOptions(profile="aggressive"))
    assert "Author's Contact Information" not in out
    assert "Body content here." in out


def test_drops_authors_contact_information_plural():
    text = "# Title\n\nAuthors' Contact Information:\n\nBody.\n"
    out = strip_repeated_byline(text, PipelineOptions(profile="aggressive"))
    assert "Authors' Contact Information" not in out
    assert "Body." in out


def test_drops_contact_email_line_within_first_50_lines():
    text = "# Title\n\nContact: alice@example.com\n\nBody.\n"
    out = strip_repeated_byline(text, PipelineOptions(profile="aggressive"))
    assert "Contact: alice@example.com" not in out
    assert "Body." in out


def test_conservative_profile_keeps_byline():
    text = (
        "# Title\n"
        "\n"
        "Author's Contact Information: Philip\n"
        "Contact: alice@example.com\n"
        "\n"
        "Body.\n"
    )
    out = strip_repeated_byline(text, PipelineOptions(profile="conservative"))
    assert "Author's Contact Information" in out
    assert "Contact: alice@example.com" in out
