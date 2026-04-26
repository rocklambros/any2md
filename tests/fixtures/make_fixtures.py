"""Regenerate synthetic test fixtures.

Run from repo root: python tests/fixtures/make_fixtures.py
Outputs deterministic PDFs and DOCX files into tests/fixtures/docs/.
Committed alongside generator so test runs don't require regeneration.
"""

from pathlib import Path
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


FIXTURES = Path(__file__).parent / "docs"


def build_multi_column_pdf() -> None:
    """Two-column layout, two pages, with a top heading and body text."""
    out = FIXTURES / "multi_column.pdf"
    c = canvas.Canvas(str(out), pagesize=LETTER)
    width, height = LETTER

    # Page 1
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1 * inch, height - 1 * inch, "Multi-Column Test Document")

    body = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
        "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
        "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris."
    )
    c.setFont("Helvetica", 10)
    # Left column
    text_left = c.beginText(1 * inch, height - 1.5 * inch)
    for line in body.split(". "):
        text_left.textLine(line.strip() + ".")
    c.drawText(text_left)
    # Right column
    text_right = c.beginText(4.5 * inch, height - 1.5 * inch)
    for line in body.split(". "):
        text_right.textLine(line.strip() + ".")
    c.drawText(text_right)

    c.showPage()

    # Page 2 — same shape, different content so dedupe doesn't merge them
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1 * inch, height - 1 * inch, "Page 2 Heading")
    c.setFont("Helvetica", 10)
    text_left = c.beginText(1 * inch, height - 1.5 * inch)
    text_left.textLine("Second-page left column content.")
    c.drawText(text_left)
    text_right = c.beginText(4.5 * inch, height - 1.5 * inch)
    text_right.textLine("Second-page right column content.")
    c.drawText(text_right)

    c.save()


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    build_multi_column_pdf()
    print(f"Wrote {FIXTURES / 'multi_column.pdf'}")


if __name__ == "__main__":
    main()
