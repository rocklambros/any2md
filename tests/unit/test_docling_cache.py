"""Unit tests for any2md/_docling_cache.py.

All tests in this file mock the Docling build callback. The real
Docling library is NOT required — Docling integration tests live in
tests/integration/test_docling_persistence.py and are gated by
pytest.mark.skipif(not has_docling()).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading

import pytest

from any2md._docling_cache import (
    CacheStats,
    _Key,
    _cache_disabled,
    _canonicalize,
    _hash_opts,
)


def test_canonicalize_passes_through_scalars():
    assert _canonicalize(None) is None
    assert _canonicalize(42) == 42
    assert _canonicalize(3.14) == 3.14
    assert _canonicalize("hello") == "hello"
    assert _canonicalize(True) is True
    assert _canonicalize(False) is False


def test_canonicalize_sorts_dict_keys():
    out = _canonicalize({"b": 1, "a": 2, "c": 3})
    assert list(out.keys()) == ["a", "b", "c"]


def test_canonicalize_sorts_lists_of_scalars():
    # Same elements in different orders must canonicalize identically.
    a = _canonicalize(["b", "a", "c"])
    b = _canonicalize(["c", "b", "a"])
    assert a == b
    assert json.dumps(a) == json.dumps(b)


def test_canonicalize_sorts_nested_lists_in_dicts():
    a = _canonicalize({"k": ["b", "a"]})
    b = _canonicalize({"k": ["a", "b"]})
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_canonicalize_handles_heterogeneous_lists():
    # Mix of dicts, strings, numbers — must produce a deterministic
    # ordering via the JSON-string sort key.
    a = _canonicalize([{"x": 1}, "hello", 42])
    b = _canonicalize([42, {"x": 1}, "hello"])
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_canonicalize_recurses_into_nested_lists_of_dicts():
    a = _canonicalize([{"b": 2}, {"a": 1}])
    b = _canonicalize([{"a": 1}, {"b": 2}])
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_key_is_frozen_and_hashable():
    k1 = _Key(fmt="pdf", digest=b"\x00" * 32)
    k2 = _Key(fmt="pdf", digest=b"\x00" * 32)
    assert k1 == k2
    assert hash(k1) == hash(k2)
    # Frozen — assignment must raise AttributeError (frozen dataclass behavior)
    with pytest.raises(AttributeError):
        k1.fmt = "docx"  # type: ignore


def test_cache_stats_default_zero():
    s = CacheStats()
    assert s.model_loads == 0
    assert s.cache_hits == 0
    assert s.cache_evictions == 0
    assert s.convert_failures == 0
    assert s.fallback_count == 0


def test_hash_opts_none_returns_zero_bytes():
    assert _hash_opts(None) == b"\x00" * 32


def test_hash_opts_stable_for_same_input():
    """Test with a synthetic Pydantic model so we don't need Docling."""
    pydantic = pytest.importorskip("pydantic")

    class M(pydantic.BaseModel):
        a: int = 1
        b: str = "x"

    h1 = _hash_opts(M())
    h2 = _hash_opts(M())
    assert h1 == h2
    assert len(h1) == 32  # sha256 raw bytes


def test_hash_opts_different_for_different_input():
    pydantic = pytest.importorskip("pydantic")

    class M(pydantic.BaseModel):
        a: int = 1

    h1 = _hash_opts(M(a=1))
    h2 = _hash_opts(M(a=2))
    assert h1 != h2


def test_hash_opts_set_field_stable_across_processes():
    """The whole reason _canonicalize exists: Pydantic serializes
    set/frozenset to list with PYTHONHASHSEED-randomized order.
    Two cold processes must produce the same hash.

    Pydantic is NOT in the [dev] extra (only in [high-fidelity] via
    transitive docling), so this test is skipped in the CI tests job
    that installs only [dev]. The subprocess imports pydantic
    directly; without the importorskip guard, subprocess.run(check=True)
    would raise ModuleNotFoundError and pytest would report ERROR.
    """
    pytest.importorskip("pydantic")
    code = textwrap.dedent("""
        from pydantic import BaseModel
        from any2md._docling_cache import _hash_opts

        class M(BaseModel):
            s: set[str] = set()

        m = M(s={"a", "b", "c", "d", "e"})
        print(_hash_opts(m).hex())
    """)
    r1 = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True,
    )
    r2 = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True,
    )
    assert r1.stdout.strip() == r2.stdout.strip(), (
        "Hash diverged across cold processes — canonicalizer is not "
        "sorting list contents (likely a regression in _canonicalize)."
    )


def test_cache_disabled_env_var(monkeypatch):
    monkeypatch.delenv("ANY2MD_DOCLING_CACHE", raising=False)
    assert _cache_disabled() is False

    for value in ("0", "off", "OFF", "FALSE", "false"):
        monkeypatch.setenv("ANY2MD_DOCLING_CACHE", value)
        assert _cache_disabled() is True

    # Empty string and any non-disable token must NOT disable
    for value in ("1", "on", "true", "yes", "", "no", "n", "disabled"):
        monkeypatch.setenv("ANY2MD_DOCLING_CACHE", value)
        assert _cache_disabled() is False


# ---------------------------------------------------------------------------
# Task 4: ConverterCache.__init__, clear, stats, _after_fork
# ---------------------------------------------------------------------------
from any2md._docling_cache import ConverterCache


def test_converter_cache_init_empty():
    cache = ConverterCache()
    assert len(cache._store) == 0
    assert cache.stats().model_loads == 0


def test_converter_cache_init_rejects_zero_maxsize():
    with pytest.raises(AssertionError, match="maxsize"):
        ConverterCache(maxsize=0)


def test_converter_cache_clear():
    cache = ConverterCache()
    cache._store[_Key(fmt="pdf", digest=b"\x00" * 32)] = object()
    assert len(cache._store) == 1
    cache.clear()
    assert len(cache._store) == 0


def test_converter_cache_stats_returns_snapshot():
    cache = ConverterCache()
    cache._stats.model_loads = 7
    snap = cache.stats()
    assert snap.model_loads == 7
    # Mutating the snapshot must not affect the cache's stats
    snap.model_loads = 999
    assert cache.stats().model_loads == 7


def test_after_fork_resets_all_state():
    cache = ConverterCache()
    cache._stats.model_loads = 5
    cache._stats.cache_hits = 3
    cache._first_load_announced = True
    cache._store[_Key(fmt="pdf", digest=b"\x00" * 32)] = object()

    cache._after_fork()

    assert cache._stats.model_loads == 0
    assert cache._stats.cache_hits == 0
    assert cache._first_load_announced is False
    assert len(cache._store) == 0


def test_register_at_fork_optional_on_windows(monkeypatch):
    """ConverterCache must construct cleanly when register_at_fork is
    unavailable (Windows). Spec L195: hasattr-guard."""
    monkeypatch.delattr(os, "register_at_fork", raising=False)
    cache = ConverterCache()
    assert cache is not None
    assert len(cache._store) == 0


# ---------------------------------------------------------------------------
# Task 5: get_or_build and _announce_first_load_if_needed
# ---------------------------------------------------------------------------


def test_get_or_build_caches_on_first_call_and_returns_same_object():
    cache = ConverterCache()
    sentinel = object()
    builds = []

    def build():
        builds.append(sentinel)
        return sentinel

    a = cache.get_or_build("pdf", None, build)
    b = cache.get_or_build("pdf", None, build)

    assert a is sentinel
    assert b is sentinel
    assert a is b
    assert len(builds) == 1
    assert cache.stats().model_loads == 1
    assert cache.stats().cache_hits == 1


def test_get_or_build_distinct_keys_distinct_builds():
    cache = ConverterCache()
    sa, sb = object(), object()

    a = cache.get_or_build("pdf", None, lambda: sa)
    b = cache.get_or_build("docx", None, lambda: sb)

    assert a is sa
    assert b is sb
    assert cache.stats().model_loads == 2


def test_env_var_disables_cache(monkeypatch):
    monkeypatch.setenv("ANY2MD_DOCLING_CACHE", "0")
    cache = ConverterCache()
    builds = []

    def build():
        o = object()
        builds.append(o)
        return o

    a = cache.get_or_build("pdf", None, build)
    b = cache.get_or_build("pdf", None, build)

    assert a is not b  # Different builds — cache bypassed
    assert cache.stats().model_loads == 0  # Counter not incremented
    assert len(builds) == 2


def test_build_raises_rolls_back_announce_flag():
    cache = ConverterCache()

    def failing_build():
        raise RuntimeError("simulated HF 503")

    with pytest.raises(RuntimeError, match="simulated"):
        cache.get_or_build("pdf", None, failing_build)

    # Flag rolled back so a subsequent successful build re-announces
    assert cache._first_load_announced is False
    assert cache.stats().model_loads == 0
    assert len(cache._store) == 0


def test_announce_returns_true_only_on_first_call():
    cache = ConverterCache()
    assert cache._announce_first_load_if_needed() is True
    assert cache._announce_first_load_if_needed() is False
    assert cache._announce_first_load_if_needed() is False


def test_maxsize_enforcement_evicts_lru():
    cache = ConverterCache(maxsize=2)
    sa, sb, sc = object(), object(), object()

    cache.get_or_build("pdf", None, lambda: sa)
    cache.get_or_build("docx", None, lambda: sb)
    # Third distinct key — must evict pdf (LRU)
    cache.get_or_build("xfmt", None, lambda: sc)

    assert cache.stats().cache_evictions >= 1
    # pdf re-build = miss (was evicted)
    sa2 = object()
    result = cache.get_or_build("pdf", None, lambda: sa2)
    assert result is sa2  # New build
    assert cache.stats().model_loads == 4


def test_two_thread_same_key_race_returns_same_object():
    cache = ConverterCache(maxsize=2)
    barrier = threading.Barrier(8)
    results = []
    results_lock = threading.Lock()

    def build():
        return object()

    def worker():
        barrier.wait()
        result = cache.get_or_build("pdf", None, build)
        with results_lock:
            results.append(result)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All 8 callers must receive the same converter
    assert all(r is results[0] for r in results)
    # Only one entry actually stored
    assert len(cache._store) == 1


def test_maxsize_1_evicts_old_keeps_new():
    cache = ConverterCache(maxsize=1)
    sa, sb = object(), object()

    a = cache.get_or_build("pdf", None, lambda: sa)
    b = cache.get_or_build("docx", None, lambda: sb)

    assert a is sa
    assert b is sb
    assert cache.stats().model_loads == 2
    assert cache.stats().cache_evictions >= 1
    # Only one entry remains
    assert len(cache._store) == 1


# ---------------------------------------------------------------------------
# Task 6: evict and evict_and_record_failure
# ---------------------------------------------------------------------------


def test_evict_returns_true_when_present_false_when_absent():
    cache = ConverterCache()
    cache.get_or_build("pdf", None, lambda: object())

    assert cache.evict("pdf", None) is True
    assert cache.evict("pdf", None) is False  # already evicted
    assert cache.stats().cache_evictions == 1


def test_evict_and_record_failure_atomic():
    cache = ConverterCache()
    cache.get_or_build("pdf", None, lambda: object())
    assert cache.stats().model_loads == 1
    assert cache.stats().convert_failures == 0

    cache.evict_and_record_failure("pdf", None)
    assert cache.stats().convert_failures == 1
    assert cache.stats().cache_evictions == 1
    assert len(cache._store) == 0


def test_evict_and_record_failure_increments_counter_even_when_absent():
    """Per spec: 'we observed a convert failure even if the slot
    was already evicted by a concurrent caller.'"""
    cache = ConverterCache()
    cache.evict_and_record_failure("pdf", None)
    # No slot existed, but failure is recorded
    assert cache.stats().convert_failures == 1
    assert cache.stats().cache_evictions == 0  # nothing to evict


# ---------------------------------------------------------------------------
# Task 7: _get_instance lazy singleton with module-level lock
# ---------------------------------------------------------------------------


def test_get_instance_returns_singleton(monkeypatch):
    import any2md._docling_cache as cm
    monkeypatch.setattr(cm, "_INSTANCE", None)

    a = cm._get_instance()
    b = cm._get_instance()
    assert a is b


def test_lazy_init_thread_safety(monkeypatch):
    """16 threads racing the first _get_instance() must observe
    exactly one ConverterCache. Without _INSTANCE_LOCK, two threads
    could each construct a cache, leaking a fork callback."""
    import any2md._docling_cache as cm
    monkeypatch.setattr(cm, "_INSTANCE", None)

    instances = []
    instances_lock = threading.Lock()
    barrier = threading.Barrier(16)

    def grab():
        barrier.wait()
        inst = cm._get_instance()
        with instances_lock:
            instances.append(inst)

    threads = [threading.Thread(target=grab) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(instances) == 16
    assert all(inst is instances[0] for inst in instances)


# ---------------------------------------------------------------------------
# Task 8: release_models, docling_session, stats (public API)
# ---------------------------------------------------------------------------


def test_release_models_clears_cache(monkeypatch):
    import any2md._docling_cache as cm
    monkeypatch.setattr(cm, "_INSTANCE", None)

    inst = cm._get_instance()
    inst.get_or_build("pdf", None, lambda: object())
    assert len(inst._store) == 1

    cm.release_models()
    assert len(inst._store) == 0


def test_docling_session_releases_on_normal_exit(monkeypatch):
    import any2md._docling_cache as cm
    monkeypatch.setattr(cm, "_INSTANCE", None)

    with cm.docling_session():
        inst = cm._get_instance()
        inst.get_or_build("pdf", None, lambda: object())
        assert len(inst._store) == 1

    assert len(inst._store) == 0


def test_docling_session_releases_on_exception(monkeypatch):
    import any2md._docling_cache as cm
    monkeypatch.setattr(cm, "_INSTANCE", None)

    inst_holder = []

    with pytest.raises(RuntimeError, match="body raises"):
        with cm.docling_session():
            inst = cm._get_instance()
            inst.get_or_build("pdf", None, lambda: object())
            inst_holder.append(inst)
            raise RuntimeError("body raises")

    assert len(inst_holder[0]._store) == 0


def test_module_level_stats_returns_snapshot(monkeypatch):
    import any2md._docling_cache as cm
    monkeypatch.setattr(cm, "_INSTANCE", None)

    inst = cm._get_instance()
    inst.get_or_build("pdf", None, lambda: object())

    s = cm.stats()
    assert s.model_loads == 1


# ---------------------------------------------------------------------------
# Task 9: get_pdf_converter, get_docx_converter, evict_on_convert_failure
# ---------------------------------------------------------------------------


def test_get_pdf_converter_uses_cache(monkeypatch):
    """Mock out Docling so we don't need it installed for unit tests."""
    import any2md._docling_cache as cm
    monkeypatch.setattr(cm, "_INSTANCE", None)

    sentinel = object()
    builds = []

    class FakeDocConverter:
        def __init__(self, *args, **kwargs):
            builds.append(self)

    class FakeFormatOption:
        def __init__(self, *args, **kwargs):
            pass

    class FakeInputFormat:
        PDF = "PDF"

    fake_docling = type(sys)("docling")
    fake_docling.datamodel = type(sys)("docling.datamodel")
    fake_docling.datamodel.base_models = type(sys)("docling.datamodel.base_models")
    fake_docling.datamodel.base_models.InputFormat = FakeInputFormat
    fake_docling.document_converter = type(sys)("docling.document_converter")
    fake_docling.document_converter.DocumentConverter = FakeDocConverter
    fake_docling.document_converter.PdfFormatOption = FakeFormatOption
    monkeypatch.setitem(sys.modules, "docling", fake_docling)
    monkeypatch.setitem(sys.modules, "docling.datamodel", fake_docling.datamodel)
    monkeypatch.setitem(
        sys.modules, "docling.datamodel.base_models",
        fake_docling.datamodel.base_models,
    )
    monkeypatch.setitem(
        sys.modules, "docling.document_converter",
        fake_docling.document_converter,
    )

    pydantic = pytest.importorskip("pydantic")

    class FakeOpts(pydantic.BaseModel):
        do_ocr: bool = False
        do_table_structure: bool = True

    opts = FakeOpts()

    a = cm.get_pdf_converter(opts)
    b = cm.get_pdf_converter(opts)

    assert a is b
    assert len(builds) == 1


def test_get_docx_converter_uses_cache(monkeypatch):
    import any2md._docling_cache as cm
    monkeypatch.setattr(cm, "_INSTANCE", None)

    builds = []

    class FakeDocConverter:
        def __init__(self):
            builds.append(self)

    fake_docling_dc = type(sys)("docling.document_converter")
    fake_docling_dc.DocumentConverter = FakeDocConverter
    monkeypatch.setitem(sys.modules, "docling", type(sys)("docling"))
    monkeypatch.setitem(sys.modules, "docling.document_converter", fake_docling_dc)

    a = cm.get_docx_converter()
    b = cm.get_docx_converter()

    assert a is b
    assert len(builds) == 1


def test_evict_on_convert_failure_short_circuits_when_disabled(monkeypatch):
    """Per spec: when ANY2MD_DOCLING_CACHE=0, the helper must NOT
    lazily construct a ConverterCache solely to bump a counter."""
    import any2md._docling_cache as cm
    monkeypatch.setattr(cm, "_INSTANCE", None)
    monkeypatch.setenv("ANY2MD_DOCLING_CACHE", "0")

    # Should not construct _INSTANCE
    cm.evict_on_convert_failure("pdf", None)
    assert cm._INSTANCE is None


def test_evict_on_convert_failure_swallows_internal_exceptions(monkeypatch):
    """Helper is called during exception handling; it MUST NOT raise
    and mask the original exception."""
    import any2md._docling_cache as cm
    monkeypatch.setattr(cm, "_INSTANCE", None)
    monkeypatch.delenv("ANY2MD_DOCLING_CACHE", raising=False)

    # Force evict_and_record_failure to raise
    inst = cm._get_instance()
    def boom(*args, **kwargs):
        raise RuntimeError("internal cache bug")
    monkeypatch.setattr(inst, "evict_and_record_failure", boom)

    # Should NOT raise
    cm.evict_on_convert_failure("pdf", None)
