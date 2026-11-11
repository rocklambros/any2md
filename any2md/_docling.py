"""Docling backend detection and lazy import helpers.

Docling is an optional dependency installed via:
    pip install "any2md[high-fidelity]"

This module never imports docling at module load. It does so inside
function bodies so that `import any2md` stays cheap when docling is
absent.
"""

from __future__ import annotations

import functools
import logging
import sys
import threading
import warnings
from importlib.util import find_spec
from pathlib import Path

from any2md._logging import safe_oneline

# One spelling of the install command, shared by every message that
# tells the user how to get Docling.
INSTALL_CMD = 'pip install "any2md[high-fidelity]"'

INSTALL_HINT_MSG = (
    "Multi-column / table-heavy PDF detected; pymupdf4llm may produce artifacts.\n"
    "        For higher fidelity, install Docling:\n"
    f"            {INSTALL_CMD}\n"
    "        Or pass --high-fidelity to require it."
)

# A mutable flag rather than a rebound bool, so install_hint changes it in
# place without a ``global`` statement and tests reset it with clear().
_hint_emitted = threading.Event()


class DoclingLogCapture:
    """Buffer WARNING+ records from a Docling logger and its children.

    A context manager around one Docling conversion. The buffering
    handler sits on ``logger_name`` so the converter can inspect what
    Docling reported and forward it into the run's warning bucket.
    Records still propagate to the root logger, so a library caller
    with its own logging setup keeps seeing them.
    """

    def __init__(self, logger_name: str) -> None:
        self._logger_name = logger_name
        self._records: list[logging.LogRecord] = []
        self._handler: logging.Handler | None = None

    def __enter__(self) -> DoclingLogCapture:
        records = self._records

        class _BufferHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _BufferHandler(level=logging.WARNING)
        logging.getLogger(self._logger_name).addHandler(handler)
        self._handler = handler
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._handler is not None:
            logging.getLogger(self._logger_name).removeHandler(self._handler)
            self._handler = None

    @property
    def records(self) -> list[logging.LogRecord]:
        return list(self._records)

    @property
    def messages(self) -> list[str]:
        return [r.getMessage() for r in self._records]


# The categories that describe a document problem. Deprecations and
# resource or import warnings describe the library, so they are left to
# the caller's normal handling.
_COUNTED_WARNINGS: tuple[type[Warning], ...] = (
    UserWarning,
    RuntimeWarning,
    SyntaxWarning,
    UnicodeWarning,
    BytesWarning,
)


# Only warnings raised from Docling's own packages describe the document.
# torch, transformers, numpy, or PIL warnings during model loading or
# conversion go to the caller's normal handling. The filter's module
# pattern matches the warning's module name, and the display hook checks
# the file the warning names.
_DOCLING_MODULE_RE = r"docling(_core)?(\.|$)"
_DOCLING_PACKAGES = ("docling", "docling_core")


@functools.cache
def _docling_package_dirs() -> tuple[Path, ...]:
    """The installed docling and docling_core package directories, resolved.

    Found once through the import system. Matching the real directories,
    not any path component named ``docling``, keeps a checkout or
    virtualenv under ``~/src/docling/`` from turning its torch or PIL
    warnings into document warnings.
    """
    dirs: list[Path] = []
    for name in _DOCLING_PACKAGES:
        try:
            spec = find_spec(name)
        except (ImportError, ValueError):
            continue
        for location in (spec.submodule_search_locations or []) if spec else []:
            dirs.append(Path(location).resolve())
    return tuple(dirs)


@functools.lru_cache(maxsize=512)
def _in_docling_package(filename: str) -> bool:
    """True when ``filename`` resolves to a file inside a Docling package.

    Cached because docling-core can raise the same warning from the same
    file once per page, and resolving a path costs system calls.
    """
    try:
        path = Path(filename).resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return any(path.is_relative_to(d) for d in _docling_package_dirs())


def _is_docling_module(name: object) -> bool:
    return isinstance(name, str) and any(
        name == pkg or name.startswith(pkg + ".") for pkg in _DOCLING_PACKAGES
    )


def _module_of(filename: str) -> object:
    """The ``__name__`` of the innermost running frame whose code is in ``filename``.

    The display hook gets the warning's file but not its module. The
    frame that raised the warning, or the caller its ``stacklevel``
    points at, is still on the stack while the hook runs.
    """
    frame = sys._getframe(1)
    while frame is not None:
        if frame.f_code.co_filename == filename:
            return frame.f_globals.get("__name__")
        frame = frame.f_back
    return None


def _from_docling(filename: str) -> bool:
    """True when a warning naming ``filename`` was raised by Docling's code.

    That holds when the file lies inside the installed docling or
    docling_core package, or when the code raising it belongs to a module
    named ``docling``, ``docling_core``, or one of their submodules.
    """
    return _in_docling_package(filename) or _is_docling_module(_module_of(filename))


class DoclingWarningCapture:
    """Record the Python warnings raised during one Docling conversion.

    docling-core reports some document problems with ``warnings.warn``
    rather than logging (for example "Provenance bbox coordinate ... is
    outside page bounds"). Python prints those raw to stderr. Inside
    this context manager a warning of a counted category raised from
    Docling's own packages (docling, docling_core) is collected
    instead, and ``messages`` returns each one sanitized to one line,
    for the run's warning bucket. They count toward ``--strict`` like
    Docling's logged warnings.

    Only those warnings are touched. An "always" filter for each counted
    category, limited to Docling's modules, goes first, so a repeat
    counts every time and a caller's "error" or "ignore" filter cannot
    raise or hide it mid-conversion. Every other warning (deprecations,
    and anything torch, transformers, numpy, or PIL raise while models
    load) meets the caller's own filters and display hook as it is
    raised, with its own module and line, and nothing is recorded or
    replayed afterward. Converters also build their Docling converter
    outside the capture, so it covers the conversion and export only.

    ``warnings.catch_warnings`` saves the process-wide filters and
    display hook on entry and restores them on exit, so a library
    caller's setup holds everywhere outside the conversion. It is not
    thread-safe, which suits the CLI's one-file-at-a-time loop. The
    capture may be entered more than once, for example around the
    conversion and then around the export, and its messages add up.
    """

    def __init__(self) -> None:
        self._context: warnings.catch_warnings | None = None
        self._messages: list[str] = []

    def __enter__(self) -> DoclingWarningCapture:
        self._context = warnings.catch_warnings()
        self._context.__enter__()
        for category in _COUNTED_WARNINGS:
            warnings.filterwarnings(
                "always", category=category, module=_DOCLING_MODULE_RE
            )
        shown = warnings.showwarning

        def collect(message, category, filename, lineno, file=None, line=None):
            try:
                ours = issubclass(category, _COUNTED_WARNINGS) and _from_docling(
                    filename
                )
            except Exception:  # noqa: BLE001 -- attribution must never raise
                # An error here would surface inside Docling's conversion
                # and turn a good result into a failure or a fallback. A
                # warning that cannot be attributed is not counted, and it
                # goes to the caller's own handling below.
                ours = False
            if ours:
                self._messages.append(
                    f"{category.__name__}: {safe_oneline(str(message))}"
                )
            else:
                shown(message, category, filename, lineno, file, line)

        warnings.showwarning = collect
        return self

    def __exit__(self, *exc: object) -> None:
        if self._context is not None:
            self._context.__exit__(*exc)
            self._context = None

    def note(self, message: str) -> None:
        """Count a problem found outside Docling, such as unreadable alt text."""
        self._messages.append(message)

    @property
    def messages(self) -> list[str]:
        return list(self._messages)


def has_docling() -> bool:
    """Return True if the docling package can be imported."""
    return find_spec("docling") is not None


def install_hint() -> None:
    """Print the install hint to stderr, at most once per process."""
    if _hint_emitted.is_set():
        return
    print(f"  WARN: {INSTALL_HINT_MSG}", file=sys.stderr)  # log-safe: literal
    _hint_emitted.set()
