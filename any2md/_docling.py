"""Docling backend detection and lazy import helpers.

Docling is an optional dependency installed via:
    pip install "any2md[high-fidelity]"

This module never imports docling at module load — it does so inside
function bodies so that `import any2md` stays cheap when docling is
absent.
"""

from __future__ import annotations

import sys
from importlib.util import find_spec

INSTALL_HINT_MSG = (
    "Multi-column / table-heavy PDF detected; pymupdf4llm may produce artifacts.\n"
    "        For higher fidelity, install Docling:\n"
    '            pip install "any2md[high-fidelity]"\n'
    "        Or pass --high-fidelity to require it."
)

_hint_emitted = False


def has_docling() -> bool:
    """Return True if the docling package can be imported."""
    return find_spec("docling") is not None


def install_hint() -> None:
    """Print the install hint to stderr — at most once per process."""
    global _hint_emitted
    if _hint_emitted:
        return
    print(f"  WARN: {INSTALL_HINT_MSG}", file=sys.stderr)  # log-safe: literal
    _hint_emitted = True
