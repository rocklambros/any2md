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
from importlib.util import find_spec

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


def has_docling() -> bool:
    """Return True if the docling package can be imported."""
    return find_spec("docling") is not None


def install_hint() -> None:
    """Print the install hint to stderr — at most once per process."""
    if _hint_emitted.is_set():
        return
    print(f"  WARN: {INSTALL_HINT_MSG}", file=sys.stderr)  # log-safe: literal
    _hint_emitted.set()
