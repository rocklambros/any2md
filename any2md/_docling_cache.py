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


class ConverterCache:
    """Thread-safe LRU cache of DocumentConverter instances.

    Build runs OUTSIDE the lock so two distinct keys can construct in
    parallel; double-check on insert prevents racing same-key builds
    from polluting the cache (one of the two builds is discarded).
    """

    def __init__(self, maxsize: int = _MAX_RESIDENT) -> None:
        assert maxsize >= 1, "maxsize must be >= 1"
        self._lock = threading.Lock()
        self._store: OrderedDict[_Key, Any] = OrderedDict()
        self._maxsize = maxsize
        self._stats = CacheStats()
        self._first_load_announced = False
        # POSIX-only: Windows has no fork(2). Guard so module imports
        # cleanly on Windows.
        if hasattr(os, "register_at_fork"):
            os.register_at_fork(after_in_child=self._after_fork)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(**vars(self._stats))

    def _after_fork(self) -> None:
        # Reassign lock (parent's may be in held state) and clear all
        # per-process state — including stats counters, since AC#1
        # uses exact equality (`model_loads == 1`) and child must
        # start fresh.
        self._lock = threading.Lock()
        self._store.clear()
        self._stats = CacheStats()
        self._first_load_announced = False

    def get_or_build(
        self, fmt: str, opts: Any | None, build: Callable[[], Any]
    ) -> Any:
        if _cache_disabled():
            return build()  # bypass entirely
        key = _Key(fmt, _hash_opts(opts))
        with self._lock:
            if key in self._store:
                self._stats.cache_hits += 1
                self._store.move_to_end(key)
                return self._store[key]
        # Build outside lock; rollback announce-flag if build raises so
        # a subsequent successful build still announces.
        announced_now = self._announce_first_load_if_needed()
        try:
            conv = build()
        except Exception:
            if announced_now:
                with self._lock:
                    self._first_load_announced = False
            raise
        with self._lock:
            self._stats.model_loads += 1
            if key not in self._store:
                self._store[key] = conv
                self._store.move_to_end(key)
                while len(self._store) > self._maxsize:
                    self._store.popitem(last=False)
                    self._stats.cache_evictions += 1
            # Defensive `.get(key, conv)` rather than `[key]`: the
            # current control flow guarantees presence (insert +
            # move_to_end places our key at MRU position; eviction
            # only pops LRU), but a future maintainer reordering
            # eviction-before-insert or moving the eviction loop
            # outside this lock would otherwise raise KeyError here.
            return self._store.get(key, conv)

    def _evict_unlocked(self, key: _Key) -> bool:
        """Drop ``key`` from the store and increment cache_evictions.
        Returns True if a slot was removed, False if the key wasn't
        present. MUST be called with ``self._lock`` already held.
        """
        if key in self._store:
            del self._store[key]
            self._stats.cache_evictions += 1
            return True
        return False

    def evict(self, fmt: str, opts: Any | None) -> bool:
        """Remove the cache entry matching (fmt, opts). Returns True
        if a slot was actually removed.

        Called by converters after `convert()` raises, to guard against
        torch internal-state contamination from a malformed input.
        """
        key = _Key(fmt, _hash_opts(opts))
        with self._lock:
            return self._evict_unlocked(key)

    def evict_and_record_failure(
        self, fmt: str, opts: Any | None
    ) -> None:
        """Atomic counterpart to `evict()` that also increments the
        convert-failure counter inside the same lock acquisition.
        Always increments (we observed a convert failure even if the
        slot was already evicted by a concurrent caller)."""
        key = _Key(fmt, _hash_opts(opts))
        with self._lock:
            self._evict_unlocked(key)
            self._stats.convert_failures += 1

    def _announce_first_load_if_needed(self) -> bool:
        """Returns True if THIS call performed the announcement (so
        the caller can roll back the flag on build failure). Returns
        False if announcement had already happened.

        Compare-and-set inside the lock so two racing first-loaders
        don't both print. I/O happens outside the lock.
        """
        with self._lock:
            if self._first_load_announced:
                return False
            self._first_load_announced = True
        # Lazy import avoids a load-time cycle: any2md.converters
        # imports from this module, so we resolve is_quiet() at call
        # time when both modules are fully initialized.
        from any2md.converters import is_quiet
        if is_quiet() or not sys.stderr.isatty():
            return True
        print("  Loading Docling models (one-time)...", file=sys.stderr)
        return True


_INSTANCE: ConverterCache | None = None
_INSTANCE_LOCK = threading.Lock()


def _get_instance() -> ConverterCache:
    """Lock-serialized lazy init. Without the lock, two threads
    racing first-call could each construct a ConverterCache; the
    losing instance's `register_at_fork` callback remains registered
    and runs on stale state at the next fork.
    """
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:  # double-check after acquiring lock
                _INSTANCE = ConverterCache()
    return _INSTANCE
