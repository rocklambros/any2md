"""Converter dispatcher for any2md."""

import sys
from pathlib import Path

from any2md.pipeline import PipelineOptions

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".txt"}


# Module-level accumulator of pipeline warnings across a single CLI run.
# `cli.main()` calls `reset_warnings()` at run start and inspects
# `collected_warnings()` at run end (e.g. for the --strict exit-code-3
# decision). Each `convert_*` function appends its `pipeline.run` warnings
# via `add_warnings()` after the pipeline returns.
_RUN_WARNINGS: list[str] = []


def reset_warnings() -> None:
    """Clear the accumulated per-run warnings. Call once at run start."""
    _RUN_WARNINGS.clear()


def add_warnings(warnings: list[str]) -> None:
    """Append warnings produced by a single `pipeline.run` call."""
    _RUN_WARNINGS.extend(warnings)


def collected_warnings() -> list[str]:
    """Return a copy of the warnings accumulated since the last reset."""
    return list(_RUN_WARNINGS)


# CLI-only output controls. The CLI sets these once at startup; converters
# consult them when emitting per-file status lines. They intentionally
# live outside `PipelineOptions` (which controls pipeline behavior).
_QUIET: bool = False
_VERBOSE: bool = False


def set_output_mode(quiet: bool = False, verbose: bool = False) -> None:
    """Configure per-file output verbosity for converters.

    `quiet` suppresses the `OK:` summary line. `verbose` is reserved for
    future per-stage timing reports (Task 7) and currently has no effect.
    """
    global _QUIET, _VERBOSE
    _QUIET = quiet
    _VERBOSE = verbose


def is_quiet() -> bool:
    return _QUIET


def is_verbose() -> bool:
    return _VERBOSE


def convert_file(
    file_path: Path,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
    strip_links_flag: bool = False,
) -> bool:
    """Dispatch to the appropriate converter based on file extension."""
    if options is None:
        options = PipelineOptions(strip_links=strip_links_flag)
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        from any2md.converters.pdf import convert_pdf
        return convert_pdf(file_path, output_dir, options=options, force=force)
    if ext == ".docx":
        from any2md.converters.docx import convert_docx
        return convert_docx(file_path, output_dir, options=options, force=force)
    if ext in (".html", ".htm"):
        from any2md.converters.html import convert_html
        return convert_html(file_path, output_dir, options=options, force=force)
    if ext == ".txt":
        from any2md.converters.txt import convert_txt
        return convert_txt(file_path, output_dir, options=options, force=force)
    print(
        f"  UNSUPPORTED: {file_path.name} (no converter for {ext})", file=sys.stderr
    )
    return False
