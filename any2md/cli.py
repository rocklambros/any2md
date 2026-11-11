"""CLI entry point for any2md."""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

from any2md import _logging
from any2md._safe_open import SkipSource, SourceFile, open_scanned
from any2md.config import (
    discover_config,
    extract_document_id_settings,
    extract_meta_overrides,
    load_toml,
)
from any2md.converters import (
    LEGACY_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    collected_warnings,
    convert_file,
    legacy_format_message,
    reset_warnings,
    set_output_mode,
)
from any2md.converters.html import convert_url
from any2md.frontmatter import filter_reserved_overrides
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
            if part not in current:
                current[part] = {}
            elif not isinstance(current[part], dict):
                raise ValueError(
                    f"--meta key conflict: {key!r} collides with an earlier value"
                )
            current = current[part]
        leaf = parts[-1]
        if leaf in current and isinstance(current[leaf], dict):
            raise ValueError(
                f"--meta key conflict: {key!r} collides with an earlier value"
            )
        current[leaf] = parsed
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
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = _deep_merge_overrides(out[key], val)
        else:
            out[key] = val
    return out


def _scan_directory(
    root: Path, recursive: bool, legacy: list[Path] | None = None
) -> list[Path]:
    """Return supported regular files under ``root``, sorted.

    Legacy ``.ppt`` and ``.xls`` files found on the way are appended to
    ``legacy`` when the caller passes a list. The caller prints their
    SKIP lines and counts them, after it drops repeat inputs, so a file
    seen by two scans is reported once and the summary matches.

    Never follows symlinks below ``root``. An untrusted document tree can
    hold a link such as ``report.txt -> ~/.ssh/id_rsa``, and following it
    would copy the target into the output (F14 CWE-59, F22 CWE-61).
    ``Path.glob`` and ``Path.rglob`` return file links, and their handling
    of directory links has changed across Python releases, so the walk
    uses ``os.scandir`` with ``follow_symlinks=False`` to get one answer
    on every supported version. Skipping directory links also rules out
    symlink loops. ``root`` itself is followed when it is a link,
    because the user named it.

    Suffixes are compared after ``os.path.normcase``, which matches the
    old glob semantics: case-insensitive on Windows, case-sensitive on
    POSIX.
    """
    suffixes = tuple(os.path.normcase(ext) for ext in SUPPORTED_EXTENSIONS)
    legacy_suffixes = tuple(os.path.normcase(ext) for ext in LEGACY_EXTENSIONS)
    found: list[Path] = []
    # An explicit stack instead of recursion keeps deep trees clear of
    # the interpreter recursion limit.
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                children = list(entries)
        except OSError as e:
            _logging.warn(f"{current} -- {e}", prefix="SKIP (unreadable)")
            continue
        for entry in children:
            path = Path(entry.path)
            try:
                if entry.is_symlink():
                    # Report only links the old scan would have picked up,
                    # so unrelated links in a tree do not flood stderr.
                    wanted = os.path.normcase(entry.name).endswith(suffixes)
                    if wanted or (recursive and entry.is_dir()):
                        _logging.warn(str(path), prefix="SKIP (symlink)")
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if recursive:
                        pending.append(path)
                    continue
                if not os.path.normcase(entry.name).endswith(suffixes):
                    # Other unsupported files stay quiet in a scan. A legacy
                    # .ppt or .xls gets one SKIP line, because the user can
                    # fix it by re-saving, and silence would hide that.
                    if legacy is not None and os.path.normcase(entry.name).endswith(
                        legacy_suffixes
                    ):
                        legacy.append(path)
                    continue
                # FIFOs and device nodes can hang the read or never end.
                if not entry.is_file(follow_symlinks=False):
                    _logging.warn(str(path), prefix="SKIP (not a regular file)")
                    continue
            except OSError as e:
                _logging.warn(f"{path} -- {e}", prefix="SKIP (unreadable)")
                continue
            found.append(path)
    return sorted(found)


def _input_identity(path: Path, scan_root: Path | None) -> tuple[int, int] | str:
    """Return a key that is equal for two inputs naming the same file.

    The device and inode pair catches every spelling of one file: a
    relative and an absolute path, a case variant on a case-insensitive
    file system, or a named link next to its target. Scanned entries use
    ``lstat`` because the scan never follows a link. A file with several
    hard links keys on its resolved path instead, so each scanned name
    still reaches open_scanned and prints its own SKIP (hard link) line.
    The resolved path is also the fallback when the file cannot be
    stat'ed, and the later open reports that error.
    """
    resolved = os.path.normcase(os.path.realpath(path))
    try:
        st = path.lstat() if scan_root is not None else path.stat()
    except OSError:
        return resolved
    if st.st_nlink > 1:
        return resolved
    return (st.st_dev, st.st_ino)


def _dedupe_inputs(
    file_paths: list[tuple[Path, Path | None]],
) -> list[tuple[Path, Path | None]]:
    """Drop repeat inputs that name a file already in the list.

    ``any2md a.pdf a.pdf``, or a directory plus a file inside it, would
    otherwise convert one file twice and report the second pass as an
    output name collision. The first occurrence wins, which keeps the
    order the user gave.
    """
    seen: set[tuple[int, int] | str] = set()
    unique: list[tuple[Path, Path | None]] = []
    for path, scan_root in file_paths:
        key = _input_identity(path, scan_root)
        if key in seen:
            continue
        seen.add(key)
        unique.append((path, scan_root))
    return unique


def main():
    script_dir = Path.cwd()
    default_output_dir = script_dir / "Text"

    parser = argparse.ArgumentParser(
        description="Convert PDF, DOCX, PPTX, XLSX, HTML, and TXT files to LLM-optimized Markdown."
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Files, directories, or URLs to convert. Supports PDF, DOCX, PPTX, XLSX, HTML, TXT files "
        "and http(s) URLs. PPTX and XLSX need the high-fidelity (Docling) install. "
        "Directories are scanned for supported files (use -r to include subdirectories). "
        "If omitted, converts all supported files in the current directory.",
    )
    parser.add_argument(
        "--input-dir",
        "-i",
        type=Path,
        help="Directory to scan for supported files (PDF, DOCX, PPTX, XLSX, HTML, TXT).",
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
        help="Force the Docling backend for PDF and DOCX (PPTX and XLSX always use it). "
        "Exit 1 if not installed.",
    )
    parser.add_argument(
        "--no-arxiv-lookup",
        action="store_true",
        help="Disable the arxiv API lookup that enriches frontmatter for "
        "PDFs whose filename matches the arxiv ID pattern (\\d{4}.\\d{4,5}). "
        "Useful in airgapped envs or when you don't want any2md to make "
        "network calls. Default: arxiv lookup is enabled.",
    )
    parser.add_argument(
        "--backend",
        choices=("docling", "pymupdf4llm", "mammoth"),
        default=None,
        help="Force a specific extraction backend. By default any2md auto-selects "
        "(prefers Docling when installed). Use 'docling' (equivalent to --high-fidelity), "
        "'pymupdf4llm' to force the lightweight PDF fallback even when Docling is installed, "
        "or 'mammoth' to force the lightweight DOCX fallback. PPTX and XLSX accept only "
        "'docling'. Mismatched format/backend combinations (e.g., --backend pymupdf4llm "
        "on a DOCX, --backend mammoth on an XLSX) error out per file.",
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
        "--no-config",
        action="store_true",
        help="Skip .any2md.toml auto-discovery (overrides default walk-up).",
    )
    parser.add_argument(
        "--docx-fallback-on-warn",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="DOCX-only. When Docling emits any msword_backend warning "
        "during conversion, auto-retry the file through mammoth and use "
        "that output instead. Docling silently drops list items on "
        "malformed input, so a warning means content is missing. "
        "Default: enabled. Disable with --no-docx-fallback-on-warn.",
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
        help="Generate an SAGE-conformant document_id of the form "
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

    discovered = None if args.no_config else discover_config()
    if discovered is not None:
        cfg = load_toml(discovered)
        overrides = _deep_merge_overrides(overrides, extract_meta_overrides(cfg))
        auto_id_prefix, auto_id_type_code = extract_document_id_settings(cfg)

    if args.meta_file is not None:
        if not args.meta_file.is_file():
            sys.stderr.write(
                f"Error: --meta-file not found: {_logging.safe_oneline(str(args.meta_file))}\n"
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
        sys.stderr.write(f"Error: {_logging.safe_oneline(str(e))}\n")
        sys.exit(1)
    overrides = _deep_merge_overrides(overrides, cli_meta)
    overrides = filter_reserved_overrides(
        overrides, source_label="--meta/--meta-file/.any2md.toml"
    )

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
        arxiv_lookup=not args.no_arxiv_lookup,
        docx_fallback_on_warn=args.docx_fallback_on_warn,
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
    # Each entry pairs a file with the directory scan that found it, or
    # with None when the user named the file. Scanned files are opened
    # relative to their scan root with no link followed (see
    # _safe_open.open_scanned). Named files follow links, because the
    # user chose them.
    file_paths: list[tuple[Path, Path | None]] = []
    # Legacy .ppt and .xls files the scans found. Each one is a skip.
    legacy_found: list[Path] = []

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
                _logging.fail(f"{f}", prefix="NOT FOUND")
                continue
            if p.is_dir():
                file_paths.extend(
                    (found, p)
                    for found in _scan_directory(p, args.recursive, legacy_found)
                )
                continue
            if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                legacy = legacy_format_message(p.suffix)
                detail = f"{f} -- {legacy}" if legacy is not None else f"{f}"
                _logging.fail(detail, prefix="UNSUPPORTED FORMAT")
                continue
            file_paths.append((p, None))
    elif args.input_dir:
        if not args.input_dir.is_dir():
            sys.stderr.write(
                f"Error: not a directory: {_logging.safe_oneline(str(args.input_dir))}\n"
            )
            sys.exit(1)
        file_paths = [
            (found, args.input_dir)
            for found in _scan_directory(args.input_dir, args.recursive, legacy_found)
        ]
    else:
        file_paths = [
            (found, script_dir)
            for found in _scan_directory(script_dir, args.recursive, legacy_found)
        ]

    file_paths = _dedupe_inputs(file_paths)
    urls = list(dict.fromkeys(urls))
    # Paired with a scan root so the identity check uses lstat, as the scan
    # that found them never followed a link.
    legacy_skips = [path for path, _ in _dedupe_inputs([(p, p) for p in legacy_found])]

    if not file_paths and not urls and not legacy_skips:
        print("No supported files to process.")
        sys.exit(0)

    # Legacy files count toward the total and the skips, so the summary
    # adds up to the number of files the run reported on.
    total = len(file_paths) + len(urls) + len(legacy_skips)
    print(
        f"Processing {total} file(s) → {_logging.safe_oneline(str(args.output_dir))}/\n"
    )
    start = time.time()
    ok = 0
    fail = 0
    skip = 0
    for path in legacy_skips:
        legacy = legacy_format_message(path.suffix)
        _logging.warn(f"{path} -- {legacy}", prefix="SKIP (legacy format)")
        skip += 1
    # Output names come from source stems, so two inputs in one run can map
    # to one file (a/x.pdf and b/x.pdf under -r, or deck.pptx next to
    # deck.docx). The second would be skipped as "exists" or, with --force,
    # overwrite the first. Names compare case-folded because the default
    # macOS and Windows file systems ignore case.
    # A name is claimed only right before conversion starts. A file that
    # is skipped (exists, too large, hard link) or fails to open writes
    # nothing, so it must not block a later file that maps to the same name.
    # The collision test still runs before the exists test, so the second
    # file of a pair reports the collision instead of SKIP (exists).
    claimed: dict[str, str] = {}

    def _collides(out_name: str, source: str) -> bool:
        key = out_name.casefold()
        if key in claimed:
            _logging.fail(
                f"{source} -- output name collision: {out_name} is already "
                f"written by {claimed[key]} in this run. Rename one of them."
            )
            return True
        return False

    def _claim(out_name: str, source: str) -> None:
        claimed[out_name.casefold()] = source

    # Process URLs
    for url in urls:
        out_name = url_to_filename(url)
        out_path = args.output_dir / out_name
        if _collides(out_name, url):
            fail += 1
            continue
        if out_path.exists() and not args.force:
            print(f"  SKIP (exists): {_logging.safe_oneline(out_name)}")
            skip += 1
            continue

        _claim(out_name, url)
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
    for file_path, scan_root in file_paths:
        # sanitize_filename strips only C0 and DEL, so C1 controls and bidi
        # overrides survive into out_name. Every status line that prints it
        # goes through safe_oneline as well.
        out_name = sanitize_filename(file_path.name)
        out_path = args.output_dir / out_name
        if _collides(out_name, str(file_path)):
            fail += 1
            continue
        if out_path.exists() and not args.force:
            print(f"  SKIP (exists): {_logging.safe_oneline(out_name)}")
            skip += 1
            continue

        source: Path | SourceFile
        if scan_root is not None:
            # The tree may have changed since the scan. open_scanned binds
            # the file to a no-follow descriptor, checks type, link count,
            # and size on that descriptor, and every later read goes
            # through it and stops at --max-file-size bytes.
            try:
                source = open_scanned(
                    scan_root, file_path.relative_to(scan_root), args.max_file_size
                )
            except SkipSource as e:
                _logging.warn(e.detail, prefix=e.prefix)
                skip += 1
                continue
            except OSError as e:
                _logging.fail(f"{file_path.name} -- {e}")
                fail += 1
                continue
        else:
            # File size check
            try:
                file_size = file_path.stat().st_size
            except OSError as e:
                _logging.fail(f"{file_path.name} -- {e}")
                fail += 1
                continue

            if file_size > args.max_file_size:
                _logging.warn(
                    f"{file_path.name} ({file_size} bytes, max {args.max_file_size})",
                    prefix="SKIP (too large)",
                )
                skip += 1
                continue
            source = file_path

        _claim(out_name, str(file_path))
        try:
            result = convert_file(
                source,
                args.output_dir,
                options=options,
                force=args.force,
            )
        finally:
            # A scanned source holds its checked descriptor open for the
            # converter. Close it now, even when the converter raised,
            # so a large batch cannot run out of descriptors.
            if isinstance(source, SourceFile):
                source.close()
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
