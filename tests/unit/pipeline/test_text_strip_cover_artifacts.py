"""Tests for T8 — strip_cover_artifacts."""

from any2md.pipeline import PipelineOptions
from any2md.pipeline.text import strip_cover_artifacts


def test_drops_qr_feedback_blurb():
    text = (
        "# Title\n"
        "\n"
        "Please share your feedback by scanning the QR code below.\n"
        "\n"
        "## Real Section\n"
        "\n"
        "Body content.\n"
    )
    out = strip_cover_artifacts(text, PipelineOptions(profile="aggressive"))
    assert "Please share your feedback" not in out
    assert "## Real Section" in out
    assert "Body content." in out


def test_drops_edition_stamp():
    text = (
        "# Document Title\n"
        "\n"
        "Customer Feedback Form Third edition 2022-02\n"
        "\n"
        "## Section\n"
        "\n"
        "Body.\n"
    )
    out = strip_cover_artifacts(text, PipelineOptions(profile="aggressive"))
    assert "Customer Feedback Form" not in out
    assert "## Section" in out


def test_drops_corrected_version_stamp():
    text = "# Title\n\nCorrected version 2022-03\n\n## Body\n\nReal content here.\n"
    out = strip_cover_artifacts(text, PipelineOptions(profile="aggressive"))
    assert "Corrected version 2022-03" not in out
    assert "## Body" in out


def test_conservative_profile_keeps_artifacts():
    text = (
        "# Title\n"
        "\n"
        "Please share your feedback via QR code.\n"
        "Corrected version 2022-03\n"
        "\n"
        "## Section\n"
    )
    out = strip_cover_artifacts(text, PipelineOptions(profile="conservative"))
    assert "Please share your feedback" in out
    assert "Corrected version 2022-03" in out


def test_only_first_30_lines_or_until_first_h2():
    # A mention of QR code appearing in the body (after the first H2) must be kept.
    head = "# Title\n\n"
    # Build a long lead-in, then an H2, then a QR mention in the body.
    lead = "\n".join([f"Line {i}" for i in range(5)])
    body = (
        "\n\n## Real Section\n\n"
        "This section discusses QR code usage in production systems.\n"
    )
    text = head + lead + body
    out = strip_cover_artifacts(text, PipelineOptions(profile="aggressive"))
    # In-body mention of QR code preserved.
    assert "QR code usage in production systems." in out
