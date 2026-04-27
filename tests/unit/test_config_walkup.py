"""Tests for discover_config boundary behavior (F3)."""

from __future__ import annotations

from any2md.config import discover_config


def test_stops_at_git_root(tmp_path):
    (tmp_path / ".any2md.toml").write_text("[meta]\n", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    sub = repo / "sub"
    sub.mkdir()
    assert discover_config(start=sub) is None


def test_stops_at_pyproject_toml(tmp_path):
    (tmp_path / ".any2md.toml").write_text("[meta]\n", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    sub = repo / "sub"
    sub.mkdir()
    assert discover_config(start=sub) is None


def test_finds_config_inside_project(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".any2md.toml").write_text("[meta]\n", encoding="utf-8")
    sub = repo / "sub"
    sub.mkdir()
    found = discover_config(start=sub)
    assert found == (repo / ".any2md.toml").resolve()


def test_returns_none_when_no_config(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").touch()
    assert discover_config(start=repo) is None


def test_honors_explicit_boundary_marker(tmp_path):
    (tmp_path / ".any2md.toml").write_text("[meta]\n", encoding="utf-8")
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / ".any2md.toml.boundary").touch()
    sub = inner / "sub"
    sub.mkdir()
    assert discover_config(start=sub) is None
