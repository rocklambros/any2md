"""Stderr/stdout sanitizer + structured-prefix log helpers.

Centralizes control-character + Unicode-spoof stripping for any string
interpolated from untrusted input (filenames, URLs, exception text,
HTTP response data). Provides ``warn`` / ``fail`` helpers that wrap
``sys.stderr.write`` with a fixed two-space indent + uppercase prefix.

Threat model: attacker-supplied tokens reach a terminal via stderr.
We strip C0/C1 control chars (incl. ANSI escapes), Unicode bidi
embeds/overrides/isolates, zero-width chars, and the BOM. Newlines
are preserved by ``_sanitize_log_text`` (multi-line tracebacks remain
readable) and stripped by ``safe_oneline`` (single-line interpolation).
"""

from __future__ import annotations

import re
import sys

_LOG_CONTROL_CHARS_RE = re.compile(
    r"["
    r"\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f"  # C0 / C1 control chars
    r"‪-‮"  # bidi embeds + override
    r"⁦-⁩"  # bidi isolates
    r"​-‏"  # zero-width + LRM/RLM
    r"﻿"  # BOM
    r"]"
)

_NEWLINE_CR_RE = re.compile(r"[\r\n]")


def _sanitize_log_text(s: str) -> str:
    """Strip control chars + Unicode bidi/zero-width. Preserves newlines."""
    return _LOG_CONTROL_CHARS_RE.sub("", s)


def safe_oneline(s: str) -> str:
    """Sanitize and collapse all newlines/CRs to single spaces.

    Use for single-line interpolation of untrusted tokens (filenames,
    URLs, ``str(exception)``) into log messages.
    """
    return _NEWLINE_CR_RE.sub(" ", _sanitize_log_text(s))


def warn(msg: str, *, prefix: str = "WARN") -> None:
    """Write ``f'  {prefix}: {sanitized}\\n'`` to stderr."""
    sys.stderr.write(f"  {prefix}: {_sanitize_log_text(msg)}\n")


def fail(msg: str, *, prefix: str = "FAIL") -> None:
    """Same as :func:`warn` with ``prefix='FAIL'``."""
    warn(msg, prefix=prefix)
