"""Process-lifetime cache of DocumentConverter instances.

Stability: experimental for v1.1.0. Public API surface:
- `release_models()` — imperative escape hatch
- `docling_session()` — contextmanager (preferred)
- `ANY2MD_DOCLING_CACHE=0` — disable cache entirely

Other names in this module are internal and may change.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator

_MAX_RESIDENT = 2  # Empirically: pdf + docx are the only construction
                   # sites; 2 slots covers 99% of mixed batches with
                   # bounded RSS (~1GB extra steady-state worst case).

_CACHE_DISABLED_ENV = "ANY2MD_DOCLING_CACHE"


def _canonicalize(obj: Any) -> Any:
    """Recursively canonicalize a JSON-able structure for stable hashing.

    `json.dumps(..., sort_keys=True)` only sorts dict keys at every
    level, NOT list contents. Pydantic v2 `model_dump(mode="json")`
    serializes `set`/`frozenset` to `list` with iteration order
    affected by `PYTHONHASHSEED` — producing different bytes for
    identical option payloads across processes. We sort lists too
    so the cache key is stable.

    Trade-off: this is lossy if a future Docling field uses list
    ORDER as semantic. None do today (verified by inspection of
    Docling 2.x `PdfPipelineOptions`). If a future field requires
    order preservation, switch this canonicalizer to a tagged form
    (e.g., wrap ordered lists in a sentinel) and update this docstring.
    """
    if isinstance(obj, dict):
        return {k: _canonicalize(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        # Sort by canonical-JSON of each element so heterogeneous
        # lists still produce a deterministic order.
        return sorted(
            (_canonicalize(item) for item in obj),
            key=lambda v: json.dumps(v, sort_keys=True),
        )
    return obj
