#!/usr/bin/env python3
"""Convert PDF files to LLM-optimized Markdown.

Usage:
    python3 pdf2md.py                        # Convert all PDFs in script directory
    python3 pdf2md.py file1.pdf file2.pdf    # Convert specific files
    python3 pdf2md.py --input-dir ./PDFs     # Convert all PDFs in a directory
    python3 pdf2md.py --force                # Overwrite existing .md files
    python3 pdf2md.py --output-dir ./Out     # Custom output directory
"""

import argparse
import re
import sys
import time
from pathlib import Path

import pymupdf
import pymupdf4llm


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "Text"


def sanitize_filename(pdf_name: str) -> str:
    """Convert a PDF filename to a sanitized .md filename.

    Matches existing convention: spaces → underscores, .pdf → .md.
    """
    stem = Path(pdf_name).stem
    # Replace spaces with underscores
    stem = stem.replace(" ", "_")
    # Replace characters problematic in filenames
    stem = re.sub(r"[,;:'\"\u2014\u2013]", "", stem)
    # Collapse multiple underscores
    stem = re.sub(r"_+", "_", stem)
    # Strip leading/trailing underscores
    stem = stem.strip("_")
    return stem + ".md"


def extract_title(markdown_text: str, fallback: str) -> str:
    """Extract the first markdown heading as the document title."""
    match = re.search(r"^#{1,3}\s+(.+)", markdown_text, re.MULTILINE)
    if match:
        title = match.group(1).strip()
        # Clean markdown formatting from title
        title = re.sub(r"\*+", "", title)
        title = re.sub(r"_+", " ", title)
        title = title.strip()
        if len(title) > 10:
            return title
    # Fallback: derive from filename
    return fallback.replace("_", " ").replace(".pdf", "").strip()


def clean_markdown(text: str) -> str:
    """Clean up markdown for LLM consumption.

    Reduces excessive whitespace while preserving structure.
    """
    # Collapse 3+ consecutive blank lines to 2
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    # Remove trailing whitespace on each line
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    # Ensure file ends with single newline
    text = text.rstrip() + "\n"
    return text


def convert_pdf(pdf_path: Path, output_dir: Path, force: bool = False) -> bool:
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

        # Extract title
        title = extract_title(md_text, pdf_path.stem)

        # Build frontmatter
        frontmatter = (
            f'---\n'
            f'title: "{title}"\n'
            f'source_file: "{pdf_path.name}"\n'
            f'pages: {page_count}\n'
            f'type: pdf\n'
            f'---\n\n'
        )

        # Clean and combine
        full_text = frontmatter + clean_markdown(md_text)

        # Write output
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(full_text, encoding="utf-8")
        print(f"  OK: {out_name} ({page_count} pages)")
        return True

    except Exception as e:
        print(f"  FAIL: {pdf_path.name} -- {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF files to LLM-optimized Markdown."
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="PDF files to convert. If omitted, converts all PDFs in the script directory.",
    )
    parser.add_argument(
        "--input-dir", "-i",
        type=Path,
        help="Directory to scan for PDF files.",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Overwrite existing .md files.",
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    args = parser.parse_args()

    # Determine which PDFs to process
    if args.files and args.input_dir:
        print("Error: cannot use both positional files and --input-dir.", file=sys.stderr)
        sys.exit(1)

    if args.files:
        pdf_paths = []
        for f in args.files:
            p = Path(f)
            if not p.is_absolute():
                p = Path.cwd() / p
            if not p.exists():
                print(f"  NOT FOUND: {f}", file=sys.stderr)
                continue
            if p.suffix.lower() != ".pdf":
                print(f"  NOT A PDF: {f}", file=sys.stderr)
                continue
            pdf_paths.append(p)
    elif args.input_dir:
        if not args.input_dir.is_dir():
            print(f"Error: not a directory: {args.input_dir}", file=sys.stderr)
            sys.exit(1)
        pdf_paths = sorted(args.input_dir.glob("*.pdf"))
    else:
        pdf_paths = sorted(SCRIPT_DIR.glob("*.pdf"))

    if not pdf_paths:
        print("No PDF files to process.")
        sys.exit(0)

    print(f"Processing {len(pdf_paths)} PDF(s) → {args.output_dir}/\n")
    start = time.time()
    ok = 0
    fail = 0
    skip = 0

    for pdf_path in pdf_paths:
        out_name = sanitize_filename(pdf_path.name)
        out_exists = (args.output_dir / out_name).exists()
        if out_exists and not args.force:
            skip += 1
        result = convert_pdf(pdf_path, args.output_dir, force=args.force)
        if result:
            if not (out_exists and not args.force):
                ok += 1
        else:
            fail += 1

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.1f}s: {ok} converted, {skip} skipped, {fail} failed.")


if __name__ == "__main__":
    main()
