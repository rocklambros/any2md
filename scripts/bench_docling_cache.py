"""Maintainer pre-release benchmark for the persistent DocumentConverter cache.

NOT part of CI (hardware variance is too high for pass/fail gating).
Run manually before tagging a release:

    python scripts/bench_docling_cache.py

Asserts:
  - exactly one model load across two same-options convert_pdf calls
  - second call wall-clock is at least 2× faster than the first

If the second-call ratio is close to 1.0, the cache is silently
no-op'ing — likely a future-Docling field with default_factory
randomness has slipped past _canonicalize. Investigate _hash_opts
output across calls.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from any2md._docling import has_docling
from any2md._docling_cache import stats
from any2md.converters.pdf import convert_pdf
from any2md.pipeline import PipelineOptions


REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "docs" / "multi_column.pdf"


def main() -> int:
    if not has_docling():
        print("ERROR: docling not installed. Run: pip install '.[high-fidelity]'")
        return 1
    if not FIXTURE.exists():
        print(f"ERROR: fixture not found at {FIXTURE}")
        return 1

    output_dir = REPO_ROOT / "Text" / "_bench"
    output_dir.mkdir(parents=True, exist_ok=True)

    options = PipelineOptions(high_fidelity=True)

    print(f"Benchmarking persistent cache against {FIXTURE.name}")
    print()

    t1 = time.perf_counter()
    convert_pdf(FIXTURE, output_dir, options=options, force=True)
    elapsed_1 = time.perf_counter() - t1
    print(f"  Call 1 (cold model load):   {elapsed_1:6.3f}s")

    t2 = time.perf_counter()
    convert_pdf(FIXTURE, output_dir, options=options, force=True)
    elapsed_2 = time.perf_counter() - t2
    print(f"  Call 2 (cache hit + warm):  {elapsed_2:6.3f}s")

    s = stats()
    print()
    print(f"  stats: model_loads={s.model_loads}, cache_hits={s.cache_hits}, "
          f"cache_evictions={s.cache_evictions}, "
          f"convert_failures={s.convert_failures}")
    print()

    # Assertion 1: exactly one model load
    if s.model_loads != 1:
        print(f"FAIL: expected model_loads == 1, got {s.model_loads}")
        return 2

    # Assertion 2: speedup ratio >= 2x
    if elapsed_1 / elapsed_2 < 2.0:
        print(
            f"FAIL: speedup ratio {elapsed_1 / elapsed_2:.2f}x < 2x threshold. "
            f"Cache may be silently no-op'ing."
        )
        return 3

    print(f"PASS: speedup {elapsed_1 / elapsed_2:.1f}x; cache is working.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
