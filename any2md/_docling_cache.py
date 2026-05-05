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

    Input contract: ``obj`` must be the output of Pydantic
    ``model_dump(mode="json")`` or equivalent JSON-clean structure
    (string-keyed dicts, JSON-scalar leaves). Non-string dict keys or
    non-JSON types (e.g., ``bytes``) are NOT supported — they will
    raise downstream from ``json.dumps`` rather than here. Callers
    that pass arbitrary user data must validate first; the cache's
    only call site (``_hash_opts``) goes through ``model_dump`` so the
    contract is upheld.
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


@dataclass(frozen=True)
class _Key:
    """Composite cache key. `fmt` is load-bearing for safety: digest
    space alone is not unique across formats (e.g., `_hash_opts(None)`
    produces the same zero bytes for both PDF and DOCX call sites).
    """
    fmt: str         # "pdf" | "docx"
    digest: bytes    # 32-byte sha256 of canonical opts json (or zeros for None)


@dataclass
class CacheStats:
    """In-process counters. No persistence, no telemetry, no opt-in.
    Exposed via the module-level `stats()` function (NOT
    `ConverterCache.stats()`, which is an instance method).

    Counters are eventually-consistent under thread contention;
    snapshots are not transactionally coherent. Acceptable for
    debug/observability use, not for control logic.
    """
    model_loads: int = 0
    cache_hits: int = 0
    cache_evictions: int = 0
    convert_failures: int = 0
    fallback_count: int = 0


def _hash_opts(opts: Any | None) -> bytes:
    """Canonical content-hash of Docling pipeline options.

    Uses Pydantic `model_dump(mode="json")` then a recursive
    canonicalizer (sorts dicts AND lists) to produce a process-stable
    digest. Non-JSON-representable types raise from `model_dump` with
    `mode="json"` — that is the desired loud-failure behavior.

    Known limitation: if a future Docling field uses
    `default_factory=lambda: random_value()` (unique per construction),
    the cache becomes a silent no-op for that field — different digest
    every call. Acceptance criterion #1 (`model_loads == 1` across two
    same-options calls) is the canary; the maintainer benchmark script
    `scripts/bench_docling_cache.py` is the periodic verifier.
    """
    if opts is None:
        return b"\x00" * 32
    canonical = _canonicalize(opts.model_dump(mode="json"))
    payload = json.dumps(canonical, sort_keys=True).encode()
    return hashlib.sha256(payload).digest()


def _cache_disabled() -> bool:
    """Read the env var on every call (intentional — supports test
    harnesses that toggle it). Cost is one `os.environ.get` per
    `get_or_build`; negligible vs the work the cache guards.

    Accepted disable values (case-insensitive): ``0``, ``off``,
    ``false``. Other values (including ``no``, ``n``, ``disabled``)
    do NOT disable the cache. Set ``ANY2MD_DOCLING_CACHE=0`` per
    the documented public surface.
    """
    return os.environ.get(_CACHE_DISABLED_ENV, "").lower() in {"0", "off", "false"}
