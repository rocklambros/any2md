"""DOCX to Markdown converter module."""

import sys
from pathlib import Path

import mammoth
import markdownify

from mdconv.utils import sanitize_filename, extract_title, clean_markdown, strip_links


def convert_docx(
    docx_path: Path,
    output_dir: Path,
    force: bool = False,
    strip_links_flag: bool = False,
) -> bool:
    """Convert a single DOCX to LLM-optimized Markdown.

    Returns True on success, False on failure.
    """
    out_name = sanitize_filename(docx_path.name)
    out_path = output_dir / out_name

    if out_path.exists() and not force:
        print(f"  SKIP (exists): {out_name}")
        return True

    try:
        with open(docx_path, "rb") as f:
            result = mammoth.convert_to_html(f)

        md_text = markdownify.markdownify(
            result.value,
            heading_style="ATX",
            strip=["img"],
        )

        # Extract title
        title = extract_title(md_text, docx_path.stem)

        # Word count (DOCX has no reliable page count)
        word_count = len(md_text.split())

        # Build frontmatter
        frontmatter = (
            f'---\n'
            f'title: "{title}"\n'
            f'source_file: "{docx_path.name}"\n'
            f'word_count: {word_count}\n'
            f'type: docx\n'
            f'---\n\n'
        )

        # Clean and combine
        full_text = frontmatter + clean_markdown(md_text)

        # Optionally strip markdown links
        if strip_links_flag:
            full_text = strip_links(full_text)

        # Write output
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(full_text, encoding="utf-8")
        print(f"  OK: {out_name} ({word_count} words)")
        return True

    except Exception as e:
        print(f"  FAIL: {docx_path.name} -- {e}", file=sys.stderr)
        return False
