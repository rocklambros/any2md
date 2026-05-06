"""Test atomic_write_text refuses to write through a symlinked target."""

from __future__ import annotations

import os
import sys

import pytest

from any2md.utils import atomic_write_text

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="symlink test POSIX-only"
)


def test_refuses_symlink_target(tmp_path):
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("ORIGINAL")
    target = tmp_path / "out.md"
    os.symlink(sentinel, target)

    with pytest.raises(ValueError, match="refusing to write through symlink"):
        atomic_write_text(target, "evil content")

    assert sentinel.read_text() == "ORIGINAL"


def test_normal_path_works(tmp_path):
    target = tmp_path / "ok.md"
    atomic_write_text(target, "hello\n")
    assert target.read_text() == "hello\n"


def test_overwrites_existing_regular_file(tmp_path):
    target = tmp_path / "exists.md"
    target.write_text("old")
    atomic_write_text(target, "new")
    assert target.read_text() == "new"
