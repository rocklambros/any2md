"""Tests for atomic_write_text (F6)."""

from __future__ import annotations

import os

import pytest

from any2md.utils import atomic_write_text


def test_writes_new_file(tmp_path):
    out = tmp_path / "x.md"
    atomic_write_text(out, "hello")
    assert out.read_text(encoding="utf-8") == "hello"


def test_overwrites_existing_file(tmp_path):
    out = tmp_path / "x.md"
    out.write_text("old", encoding="utf-8")
    atomic_write_text(out, "new")
    assert out.read_text(encoding="utf-8") == "new"


def test_refuses_pre_existing_symlink(tmp_path):
    target = tmp_path / "real.md"
    target.write_text("victim", encoding="utf-8")
    link = tmp_path / "out.md"
    os.symlink(target, link)
    with pytest.raises(ValueError, match="symlink"):
        atomic_write_text(link, "evil")
    assert target.read_text(encoding="utf-8") == "victim"


def test_no_partial_file_on_exception(tmp_path, monkeypatch):
    out = tmp_path / "x.md"

    def boom(*_a, **_kw):
        raise OSError("disk full")

    monkeypatch.setattr("any2md.utils.os.replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(out, "hello")
    assert not out.exists()
    leftovers = list(tmp_path.glob(".any2md-*.tmp"))
    assert leftovers == []


def test_creates_parent_dir_if_missing(tmp_path):
    out = tmp_path / "deep" / "nested" / "x.md"
    atomic_write_text(out, "hi")
    assert out.read_text(encoding="utf-8") == "hi"
