"""Converter dispatcher for any2md."""

from pathlib import Path

from any2md import _logging
from any2md._safe_open import SourceFile, as_source
from any2md.pipeline import PipelineOptions

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".html",
    ".htm",
    ".txt",
}

# Pre-2007 binary Office formats. No any2md backend reads them, and a
# user who points any2md at one should learn why it was not converted
# and what to do, instead of seeing it ignored. Maps each extension to
# the application name and the format to re-save as.
LEGACY_EXTENSIONS = {
    ".ppt": ("PowerPoint", ".pptx"),
    ".xls": ("Excel", ".xlsx"),
}


def legacy_format_message(ext: str) -> str | None:
    """Return the re-save hint for a legacy binary extension, else None."""
    entry = LEGACY_EXTENSIONS.get(ext.lower())
    if entry is None:
        return None
    app, modern = entry
    return (
        f"legacy binary {app} format ({ext}) is not supported. "
        f"Save it as {modern} and convert that file."
    )


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
    file_path: Path | SourceFile,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
    strip_links_flag: bool = False,
) -> bool:
    """Dispatch to the appropriate converter based on file extension.

    ``file_path`` is a path the converter opens itself, or a
    ``SourceFile`` from ``_safe_open.open_scanned`` whose bytes are
    already read.
    """
    if options is None:
        options = PipelineOptions(strip_links=strip_links_flag)
    file_path = as_source(file_path)
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        from any2md.converters.pdf import convert_pdf

        return convert_pdf(file_path, output_dir, options=options, force=force)
    if ext == ".docx":
        from any2md.converters.docx import convert_docx

        return convert_docx(file_path, output_dir, options=options, force=force)
    if ext in (".pptx", ".xlsx"):
        from any2md.converters.office import convert_office

        return convert_office(
            file_path, output_dir, ext[1:], options=options, force=force
        )
    if ext in (".html", ".htm"):
        from any2md.converters.html import convert_html

        return convert_html(file_path, output_dir, options=options, force=force)
    if ext == ".txt":
        from any2md.converters.txt import convert_txt

        return convert_txt(file_path, output_dir, options=options, force=force)
    legacy = legacy_format_message(file_path.suffix)
    if legacy is not None:
        _logging.fail(f"{file_path.name} -- {legacy}", prefix="UNSUPPORTED")
        return False
    _logging.fail(f"{file_path.name} (no converter for {ext})", prefix="UNSUPPORTED")
    return False
