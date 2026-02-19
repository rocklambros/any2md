"""CLI entry point for mdconv."""

import argparse
import sys
import time
from pathlib import Path

from mdconv.converters import convert_file, SUPPORTED_EXTENSIONS
from mdconv.converters.html import convert_html, fetch_url
from mdconv.utils import sanitize_filename, url_to_filename

SCRIPT_DIR = Path.cwd()
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "Text"


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF, DOCX, and HTML files to LLM-optimized Markdown."
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Files or URLs to convert. Supports PDF, DOCX, HTML files and http(s) URLs. "
        "If omitted, converts all supported files in the current directory.",
    )
    parser.add_argument(
        "--input-dir", "-i",
        type=Path,
        help="Directory to scan for supported files (PDF, DOCX, HTML).",
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
    parser.add_argument(
        "--strip-links",
        action="store_true",
        help="Remove markdown links, keeping only the link text.",
    )
    args = parser.parse_args()

    # Determine which files to process
    if args.files and args.input_dir:
        print("Error: cannot use both positional files and --input-dir.", file=sys.stderr)
        sys.exit(1)

    urls = []
    file_paths = []

    if args.files:
        for f in args.files:
            # URL detection
            if f.startswith("http://") or f.startswith("https://"):
                urls.append(f)
                continue

            p = Path(f)
            if not p.is_absolute():
                p = Path.cwd() / p
            if not p.exists():
                print(f"  NOT FOUND: {f}", file=sys.stderr)
                continue
            if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                print(f"  UNSUPPORTED FORMAT: {f}", file=sys.stderr)
                continue
            file_paths.append(p)
    elif args.input_dir:
        if not args.input_dir.is_dir():
            print(f"Error: not a directory: {args.input_dir}", file=sys.stderr)
            sys.exit(1)
        file_paths = sorted(
            p for ext in SUPPORTED_EXTENSIONS
            for p in args.input_dir.glob(f"*{ext}")
        )
    else:
        file_paths = sorted(
            p for ext in SUPPORTED_EXTENSIONS
            for p in SCRIPT_DIR.glob(f"*{ext}")
        )

    if not file_paths and not urls:
        print("No supported files to process.")
        sys.exit(0)

    total = len(file_paths) + len(urls)
    print(f"Processing {total} file(s) → {args.output_dir}/\n")
    start = time.time()
    ok = 0
    fail = 0
    skip = 0

    # Process URLs
    for url in urls:
        html_content, error = fetch_url(url)
        if error:
            print(f"  FAIL: {url} -- {error}", file=sys.stderr)
            fail += 1
            continue

        out_name = url_to_filename(url)
        out_exists = (args.output_dir / out_name).exists()
        if out_exists and not args.force:
            skip += 1

        result = convert_html(
            None,
            args.output_dir,
            force=args.force,
            strip_links_flag=args.strip_links,
            source_url=url,
            html_content=html_content,
        )
        if result:
            if not (out_exists and not args.force):
                ok += 1
        else:
            fail += 1

    # Process local files
    for file_path in file_paths:
        out_name = sanitize_filename(file_path.name)
        out_exists = (args.output_dir / out_name).exists()
        if out_exists and not args.force:
            skip += 1
        result = convert_file(
            file_path,
            args.output_dir,
            force=args.force,
            strip_links_flag=args.strip_links,
        )
        if result:
            if not (out_exists and not args.force):
                ok += 1
        else:
            fail += 1

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.1f}s: {ok} converted, {skip} skipped, {fail} failed.")
