"""Shared pytest fixtures for any2md."""

from pathlib import Path

import pytest


@pytest.fixture
def fixture_dir() -> Path:
    """Path to tests/fixtures/docs/."""
    return Path(__file__).parent / "fixtures" / "docs"


@pytest.fixture
def snapshot_dir() -> Path:
    """Path to tests/fixtures/snapshots/."""
    return Path(__file__).parent / "fixtures" / "snapshots"


@pytest.fixture
def tmp_output_dir(tmp_path) -> Path:
    """Per-test output directory under pytest tmp_path."""
    out = tmp_path / "output"
    out.mkdir()
    return out


@pytest.fixture(autouse=True)
def _reset_docling_cache():
    """Project-wide: clear the persistent DocumentConverter cache
    BEFORE and AFTER every test, ensuring no state leaks across
    tests in either direction.

    Bidirectional cleanup: pre-yield handles state left by a prior
    aborted session; post-yield handles state set by the current
    test for the next one. Cost on the release path: ~2.47s × ~6
    Docling integration tests = ~15s added CI time. Acceptable.
    """
    from any2md import release_models
    release_models()
    yield
    release_models()
