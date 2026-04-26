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
