"""CLI entry point for any2md."""

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from any2md.config import (
    discover_config,
    extract_document_id_settings,
    extract_meta_overrides,
    load_toml,
)
from any2md.converters import (
    SUPPORTED_EXTENSIONS,
    collected_warnings,
    convert_file,
    reset_warnings,
    set_output_mode,
)
from any2md.converters.html import convert_url
from any2md.pipeline import PipelineOptions
from any2md.utils import sanitize_filename, url_to_filename

# Default max file size: 100 MB
_DEFAULT_MAX_FILE_SIZE = 100 * 1024 * 1024


def parse_meta_args(meta_args: list[str]) -> dict[str, Any]:
    """Parse repeated ``--meta KEY=VAL`` arguments into a nested dict.

    - ``KEY`` may be dotted (``a.b.c``) → builds a nested ``dict``.
    - ``VAL`` containing commas becomes a ``list[str]`` (whitespace-trimmed).
    - Otherwise ``VAL`` is the trimmed string.

    Raises ``ValueError`` for malformed entries.
    """
    out: dict[str, Any] = {}
    for arg in meta_args:
        if "=" not in arg:
            raise ValueError(f"--meta value must be KEY=VAL: {arg!r}")
        key, val = arg.split("=", 1)
        if "," in val:
            parsed: Any = [v.strip() for v in val.split(",") if v.strip()]
        else:
            parsed = val.strip()
        parts = key.split(".")
        current = out
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = parsed
    return out


def _deep_merge_overrides(
    base: dict[str, Any], overrides: dict[str, Any]
) -> dict[str, Any]:
    """Deep-merge ``overrides`` into ``base`` (CLI-side mirror of frontmatter._deep_merge).

    Used to combine config-file overrides with CLI ``--meta`` overrides
    before forwarding the result into ``PipelineOptions``.
    """
    out = dict(base)
    for key, val in overrides.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(val, dict)
        ):
            out[key] = _deep_merge_overrides(out[key], val)
        else:
            out[key] = val
    return out


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
    parser.add_argument(
        "--backend",
        choices=("docling", "pymupdf4llm", "mammoth"),
        default=None,
        help="Force a specific extraction backend. By default any2md auto-selects "
        "(prefers Docling when installed). Use 'docling' (equivalent to --high-fidelity), "
        "'pymupdf4llm' to force the lightweight PDF fallback even when Docling is installed, "
        "or 'mammoth' to force the lightweight DOCX fallback. Mismatched format/backend "
        "combinations (e.g., --backend pymupdf4llm on a DOCX) error out per file.",
    )
    parser.add_argument(
        "--ocr-figures",
        action="store_true",
        help="OCR text inside figures (PDF Docling path). Implies --high-fidelity.",
    )
    parser.add_argument(
        "--save-images",
        action="store_true",
        help="Save extracted images to <output>/images/ and reference them. Implies --high-fidelity.",
    )
    parser.add_argument(
        "--profile",
        choices=("conservative", "aggressive", "maximum"),
        default="aggressive",
        help="Token-minimization aggressiveness (default: aggressive). "
        "'conservative' skips TOC dedupe and footnote-marker stripping; "
        "'maximum' additionally turns on --strip-links.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Promote pipeline validation warnings to errors (exit 3).",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress per-file 'OK:' lines. Errors and final summary still print.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print pipeline stage timings per file.",
    )
    parser.add_argument(
        "--auto-id",
        action="store_true",
        help="Generate an SSRM-conformant document_id of the form "
        "{PREFIX}-{YYYY}-{TYPE}-{SHA8}. Defaults: PREFIX=LOCAL, TYPE=DOC. "
        "Override via .any2md.toml [document_id] (publisher_prefix, type_code).",
    )
    parser.add_argument(
        "--meta",
        action="append",
        default=[],
        metavar="KEY=VAL",
        help="Override frontmatter field. Repeatable. Arrays use comma "
        "syntax. Nested keys use dot syntax (e.g. "
        "generation_metadata.authored_by=human).",
    )
    parser.add_argument(
        "--meta-file",
        type=Path,
        default=None,
        help="TOML file with frontmatter defaults under [meta] and "
        "auto-id settings under [document_id]. When omitted, "
        ".any2md.toml is auto-discovered by walking up from cwd.",
    )
    args = parser.parse_args()

    # Resolution order: discovered .any2md.toml → --meta-file → --meta
    # (highest priority last). Each layer deep-merges over the previous.
    overrides: dict[str, Any] = {}
    auto_id_prefix, auto_id_type_code = "LOCAL", "DOC"

    discovered = discover_config()
    if discovered is not None:
        cfg = load_toml(discovered)
        overrides = _deep_merge_overrides(overrides, extract_meta_overrides(cfg))
        auto_id_prefix, auto_id_type_code = extract_document_id_settings(cfg)

    if args.meta_file is not None:
        if not args.meta_file.is_file():
            print(
                f"Error: --meta-file not found: {args.meta_file}", file=sys.stderr
            )
            sys.exit(1)
        cfg = load_toml(args.meta_file)
        overrides = _deep_merge_overrides(overrides, extract_meta_overrides(cfg))
        # Only adopt id settings if the file actually declared them — a
        # bare --meta-file shouldn't reset values pulled from .any2md.toml.
        id_section = cfg.get("document_id", {}) if isinstance(cfg, dict) else {}
        if isinstance(id_section, dict):
            if "publisher_prefix" in id_section:
                auto_id_prefix = id_section["publisher_prefix"]
            if "type_code" in id_section:
                auto_id_type_code = id_section["type_code"]

    try:
        cli_meta = parse_meta_args(args.meta)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    overrides = _deep_merge_overrides(overrides, cli_meta)

    if (
        args.high_fidelity
        or args.ocr_figures
        or args.save_images
        or args.backend == "docling"
    ):
        from any2md._docling import has_docling, INSTALL_HINT_MSG
        if not has_docling():
            print(
                f"  ERROR: Docling required for --high-fidelity / --ocr-figures / --save-images / --backend docling.\n"
                f"  {INSTALL_HINT_MSG}",
                file=sys.stderr,
            )
            sys.exit(1)

    # --profile maximum implies --strip-links per spec §4.4.
    effective_strip_links = args.strip_links or (args.profile == "maximum")

    options = PipelineOptions(
        profile=args.profile,
        strip_links=effective_strip_links,
        high_fidelity=args.high_fidelity or args.ocr_figures or args.save_images,
        ocr_figures=args.ocr_figures,
        save_images=args.save_images,
        strict=args.strict,
        auto_id=args.auto_id,
        auto_id_prefix=auto_id_prefix,
        auto_id_type_code=auto_id_type_code,
        frontmatter_overrides=overrides or None,
        backend=args.backend,
    )

    # CLI-only output controls (not part of PipelineOptions).
    set_output_mode(quiet=args.quiet, verbose=args.verbose)
    reset_warnings()

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
    warnings_seen = collected_warnings()
    warn_suffix = (
        f" {len(warnings_seen)} warning(s) — pass --strict to fail on warnings."
        if warnings_seen
        else ""
    )
    print(
        f"\nDone in {elapsed:.1f}s: {ok} converted, {skip} skipped, {fail} failed."
        f"{warn_suffix}"
    )

    # Exit code policy:
    #   0 = success
    #   1 = usage / install error (argparse uses 2 by default; we use 1
    #       for explicit pre-flight failures like missing Docling)
    #   2 = >= 1 file failed entirely (HARD failure)
    #   3 = >= 1 pipeline warning AND --strict (no hard failures)
    # Failures take precedence over strict warnings.
    if fail > 0:
        sys.exit(2)
    had_strict_warning = args.strict and bool(warnings_seen)
    if had_strict_warning:
        sys.exit(3)
    sys.exit(0)
