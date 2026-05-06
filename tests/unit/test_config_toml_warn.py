"""Test load_toml emits a sanitized warning on parse error."""

from __future__ import annotations

from pathlib import Path

from any2md.config import load_toml


def test_warns_on_malformed_toml(tmp_path, capsys):
    path = tmp_path / ".any2md.toml"
    path.write_text("invalid =\n  ===toml")

    result = load_toml(path)

    captured = capsys.readouterr()
    assert result == {}
    assert "WARN: failed to parse" in captured.err


def test_warn_is_sanitized(tmp_path, capsys):
    """A path containing a control char should not appear verbatim in stderr."""
    # We don't actually need a file to exist — load_toml will fail on read,
    # and the warn message must be sanitized.
    p = Path(str(tmp_path / "name") + "\x00")
    load_toml(p)
    captured = capsys.readouterr()
    assert "\x00" not in captured.err


def test_no_warn_on_missing_file(tmp_path, capsys):
    """A file that doesn't exist should not warn (returns {} silently)."""
    result = load_toml(tmp_path / "absent.toml")
    captured = capsys.readouterr()
    assert result == {}
    assert "WARN" not in captured.err
