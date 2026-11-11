"""Docling backend detection and lazy import helpers.

Docling is an optional dependency installed via:
    pip install "any2md[high-fidelity]"

This module never imports docling at module load — it does so inside
function bodies so that `import any2md` stays cheap when docling is
absent.
"""

from __future__ import annotations

import logging
import sys
import threading
import warnings
from importlib.util import find_spec

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


class DoclingWarningCapture:
    """Record the Python warnings raised during one Docling conversion.

    docling-core reports some document problems with ``warnings.warn``
    rather than logging (for example "Provenance bbox coordinate ... is
    outside page bounds"). Python prints those raw to stderr. Inside
    this context manager every warning is recorded instead, and
    ``messages`` returns the ones that describe the document, each
    sanitized to one line, for the run's warning bucket. They count
    toward ``--strict`` like Docling's logged warnings.

    Deprecation-style categories describe the library, not the document,
    so they are not counted. They are issued again on exit, where the
    caller's own filters decide whether anyone sees them.

    ``warnings.catch_warnings`` saves the process-wide filters on entry
    and restores them on exit, so a library caller's filters hold
    everywhere outside the conversion. It is not thread-safe, which
    suits the CLI's one-file-at-a-time loop.
    """

    _NOT_COUNTED: tuple[type[Warning], ...] = (
        DeprecationWarning,
        PendingDeprecationWarning,
        FutureWarning,
        ImportWarning,
        ResourceWarning,
    )

    def __init__(self) -> None:
        self._context: warnings.catch_warnings | None = None
        self._log: list[warnings.WarningMessage] = []

    def __enter__(self) -> DoclingWarningCapture:
        self._context = warnings.catch_warnings(record=True)
        # The list starts empty and fills as warnings arrive, so keep this
        # exact object. record=True always returns one.
        log = self._context.__enter__()
        self._log = log if log is not None else []
        # "always" so a warning repeated at the same source line is
        # counted every time, not only on its first appearance.
        warnings.simplefilter("always")
        return self

    def __exit__(self, *exc: object) -> None:
        if self._context is None:
            return
        self._context.__exit__(*exc)
        self._context = None
        for w in self._log:
            if issubclass(w.category, self._NOT_COUNTED):
                warnings.warn_explicit(w.message, w.category, w.filename, w.lineno)

    @property
    def messages(self) -> list[str]:
        return [
            f"{w.category.__name__}: {safe_oneline(str(w.message))}"
            for w in self._log
            if not issubclass(w.category, self._NOT_COUNTED)
        ]


def has_docling() -> bool:
    """Return True if the docling package can be imported."""
    return find_spec("docling") is not None


def install_hint() -> None:
    """Print the install hint to stderr — at most once per process."""
    if _hint_emitted.is_set():
        return
    print(f"  WARN: {INSTALL_HINT_MSG}", file=sys.stderr)  # log-safe: literal
    _hint_emitted.set()
