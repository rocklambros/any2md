"""PDF to Markdown converter."""

import sys
from pathlib import Path

import pymupdf
import pymupdf4llm

from mdconv.utils import sanitize_filename, extract_title, clean_markdown, strip_links, escape_yaml_string


def convert_pdf(
    pdf_path: Path,
    output_dir: Path,
    force: bool = False,
    strip_links_flag: bool = False,
) -> bool:
    """Convert a single PDF to LLM-optimized Markdown.

    Returns True on success, False on failure.
    """
    out_name = sanitize_filename(pdf_path.name)
    out_path = output_dir / out_name

    if out_path.exists() and not force:
        print(f"  SKIP (exists): {out_name}")
        return True

    try:
        # Get page count
        doc = pymupdf.open(str(pdf_path))
        page_count = len(doc)
        doc.close()

        # Convert to markdown
        md_text = pymupdf4llm.to_markdown(
            str(pdf_path),
            write_images=False,
            show_progress=False,
            force_text=True,
        )

        # Clean markdown content
        md_text = clean_markdown(md_text)

        # Optionally strip links (before frontmatter)
        if strip_links_flag:
            md_text = strip_links(md_text)

        # Extract title
        title = extract_title(md_text, pdf_path.stem)

        # Build frontmatter (escape values for valid YAML)
        frontmatter = (
            f'---\n'
            f'title: "{escape_yaml_string(title)}"\n'
            f'source_file: "{escape_yaml_string(pdf_path.name)}"\n'
            f'pages: {page_count}\n'
            f'type: pdf\n'
            f'---\n\n'
        )

        full_text = frontmatter + md_text

        # Write output
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(full_text, encoding="utf-8")
        print(f"  OK: {out_name} ({page_count} pages)")
        return True

    except Exception as e:
        print(f"  FAIL: {pdf_path.name} -- {e}", file=sys.stderr)
        return False
