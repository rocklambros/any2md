"""Config file loader for any2md.

Discovers ``.any2md.toml`` by walking up from cwd. The ``[meta]`` table
is treated as frontmatter overrides (deep-merged below ``--meta-file``
and CLI ``--meta`` arguments). The ``[document_id]`` table provides
``publisher_prefix`` / ``type_code`` overrides for ``--auto-id``.

TOML parsing uses stdlib ``tomllib`` (any2md requires Python 3.11+).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from any2md import _logging


def load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file. Returns ``{}`` on any failure.

    Errors are intentionally swallowed: a malformed config file should
    not block conversion. Callers that need strict validation should
    parse the file themselves.
    """
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}  # silent — discovery walks ancestors and most won't have one
    except (OSError, ValueError) as e:
        _logging.warn(f"failed to parse {path}: {e}")
        return {}


_PROJECT_BOUNDARY_MARKERS = (
    ".git",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    ".any2md.toml.boundary",
)


def discover_config(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` (default: cwd) looking for ``.any2md.toml``.

    Stops at the first ancestor containing a project boundary marker
    (``.git``, ``pyproject.toml``, ``setup.py``, ``setup.cfg``,
    ``package.json``, or ``.any2md.toml.boundary``) so config in
    unrelated parent directories cannot leak into a project's run.
    """
    cur = (start or Path.cwd()).resolve()
    while True:
        candidate = cur / ".any2md.toml"
        if candidate.is_file():
            return candidate
        if any((cur / m).exists() for m in _PROJECT_BOUNDARY_MARKERS):
            return None
        if cur.parent == cur:
            return None
        cur = cur.parent


def extract_meta_overrides(config: dict[str, Any]) -> dict[str, Any]:
    """Extract the ``[meta]`` section as a flat overrides dict."""
    section = config.get("meta", {})
    if not isinstance(section, dict):
        return {}
    return dict(section)


def extract_document_id_settings(config: dict[str, Any]) -> tuple[str, str]:
    """Extract ``publisher_prefix`` and ``type_code`` from ``[document_id]``.

    Returns ``(prefix, type_code)`` defaulting to ``("LOCAL", "DOC")``
    when the section or keys are absent.
    """
    section = config.get("document_id", {})
    if not isinstance(section, dict):
        return ("LOCAL", "DOC")
    return (
        section.get("publisher_prefix", "LOCAL"),
        section.get("type_code", "DOC"),
    )
