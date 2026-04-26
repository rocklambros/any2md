"""CLI entry point for any2md."""

import argparse
import sys
import time
from pathlib import Path

from any2md.converters import convert_file, SUPPORTED_EXTENSIONS
from any2md.converters.html import convert_url
from any2md.pipeline import PipelineOptions
from any2md.utils import sanitize_filename, url_to_filename

# Default max file size: 100 MB
_DEFAULT_MAX_FILE_SIZE = 100 * 1024 * 1024


def main():
    script_dir = Path.cwd()
    default_output_dir = script_dir / "Text"

    parser = argparse.ArgumentParser(
        description="Convert PDF, DOCX, HTML, and TXT files to LLM-optimized Markdown."
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Files, directories, or URLs to convert. Supports PDF, DOCX, HTML files and http(s) URLs. "
        "Directories are scanned for supported files (use -r to include subdirectories). "
        "If omitted, converts all supported files in the current directory.",
    )
    parser.add_argument(
        "--input-dir",
        "-i",
        type=Path,
        help="Directory to scan for supported files (PDF, DOCX, HTML).",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Overwrite existing .md files.",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=default_output_dir,
        help=f"Output directory (default: {default_output_dir}).",
    )
    parser.add_argument(
        "--strip-links",
        action="store_true",
        help="Remove markdown links, keeping only the link text.",
    )
    parser.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help="Recursively scan subdirectories for supported files.",
    )
    parser.add_argument(
        "--max-file-size",
        type=int,
        default=_DEFAULT_MAX_FILE_SIZE,
        help=f"Maximum file size in bytes (default: {_DEFAULT_MAX_FILE_SIZE}).",
    )
    parser.add_argument(
        "--high-fidelity",
        "-H",
        action="store_true",
        help="Force the Docling backend (PDF/DOCX). Exit 1 if not installed.",
    )
    args = parser.parse_args()

    if args.high_fidelity:
        from any2md._docling import has_docling, INSTALL_HINT_MSG
        if not has_docling():
            print(
                f"  ERROR: --high-fidelity requested but docling is not installed.\n"
                f"  {INSTALL_HINT_MSG}",
                file=sys.stderr,
            )
            sys.exit(1)

    options = PipelineOptions(
        strip_links=args.strip_links,
        high_fidelity=args.high_fidelity,
    )

    # Determine which files to process
    if args.files and args.input_dir:
        print(
            "Error: cannot use both positional files and --input-dir.", file=sys.stderr
        )
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
            if p.is_dir():
                glob_method = p.rglob if args.recursive else p.glob
                file_paths.extend(
                    sorted(
                        fp
                        for ext in SUPPORTED_EXTENSIONS
                        for fp in glob_method(f"*{ext}")
                    )
                )
                continue
            if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                print(f"  UNSUPPORTED FORMAT: {f}", file=sys.stderr)
                continue
            file_paths.append(p)
    elif args.input_dir:
        if not args.input_dir.is_dir():
            print(f"Error: not a directory: {args.input_dir}", file=sys.stderr)
            sys.exit(1)
        glob_method = args.input_dir.rglob if args.recursive else args.input_dir.glob
        file_paths = sorted(
            p for ext in SUPPORTED_EXTENSIONS for p in glob_method(f"*{ext}")
        )
    else:
        glob_method = script_dir.rglob if args.recursive else script_dir.glob
        file_paths = sorted(
            p for ext in SUPPORTED_EXTENSIONS for p in glob_method(f"*{ext}")
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
        out_name = url_to_filename(url)
        out_path = args.output_dir / out_name
        if out_path.exists() and not args.force:
            print(f"  SKIP (exists): {out_name}")
            skip += 1
            continue

        result = convert_url(
            url,
            args.output_dir,
            options=options,
            force=args.force,
        )
        if result:
            ok += 1
        else:
            fail += 1

    # Process local files
    for file_path in file_paths:
        out_name = sanitize_filename(file_path.name)
        out_path = args.output_dir / out_name
        if out_path.exists() and not args.force:
            print(f"  SKIP (exists): {out_name}")
            skip += 1
            continue

        # File size check
        try:
            file_size = file_path.stat().st_size
        except OSError as e:
            print(f"  FAIL: {file_path.name} -- {e}", file=sys.stderr)
            fail += 1
            continue

        if file_size > args.max_file_size:
            print(
                f"  SKIP (too large): {file_path.name} ({file_size} bytes, max {args.max_file_size})",
                file=sys.stderr,
            )
            skip += 1
            continue

        result = convert_file(
            file_path,
            args.output_dir,
            options=options,
            force=args.force,
        )
        if result:
            ok += 1
        else:
            fail += 1

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.1f}s: {ok} converted, {skip} skipped, {fail} failed.")
