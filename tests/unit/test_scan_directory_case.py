"""Directory scans match extensions the way the platform compares names.

``Path.glob`` matched case-insensitively on Windows and case-sensitively
on POSIX. The symlink-safe scanner must keep that, so ``REPORT.TXT`` is
still picked up on Windows. No symlinks here, so these run everywhere.
"""

from __future__ import annotations

import os

from any2md import cli


def test_uppercase_extension_follows_platform_case_rules(tmp_path):
    (tmp_path / "REPORT.TXT").write_text("hello", encoding="utf-8")
    found = cli._scan_directory(tmp_path, recursive=False)
    expected = os.path.normcase("A.TXT") == os.path.normcase("a.txt")
    assert (found == [tmp_path / "REPORT.TXT"]) is expected


def test_case_insensitive_platform_matches_uppercase(tmp_path, monkeypatch):
    # Stand in for Windows, where normcase lowercases names.
    monkeypatch.setattr(cli.os.path, "normcase", str.lower)
    (tmp_path / "REPORT.TXT").write_text("hello", encoding="utf-8")
    (tmp_path / "notes.Htm").write_text("hello", encoding="utf-8")
    found = cli._scan_directory(tmp_path, recursive=False)
    assert sorted(p.name for p in found) == ["REPORT.TXT", "notes.Htm"]
