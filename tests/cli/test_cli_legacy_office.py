"""Legacy binary .ppt and .xls files get a clear message, not silence."""

from __future__ import annotations

import sys

import pytest

from any2md import cli
from any2md.converters import convert_file


def _run(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["any2md", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return exc.value.code


@pytest.mark.parametrize(
    ("name", "app", "modern"),
    [("deck.ppt", "PowerPoint", ".pptx"), ("BOOK.XLS", "Excel", ".xlsx")],
)
def test_named_legacy_file_is_reported(
    monkeypatch, tmp_path, capsys, name, app, modern
):
    legacy = tmp_path / name
    legacy.write_bytes(b"\xd0\xcf\x11\xe0legacy")

    _run(monkeypatch, [str(legacy), "-o", str(tmp_path / "out")])

    err = capsys.readouterr().err
    ext = legacy.suffix
    assert (
        f"  UNSUPPORTED FORMAT: {legacy} -- legacy binary {app} format ({ext}) "
        f"is not supported. Save it as {modern} and convert that file."
    ) in err.splitlines()


def test_scanned_legacy_file_is_skipped_with_a_note(monkeypatch, tmp_path, capsys):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "old.xls").write_bytes(b"\xd0\xcf\x11\xe0legacy")
    (corpus / "notes.rtf").write_text("{\\rtf1 other unsupported}")
    (corpus / "keep.txt").write_text("Plain notes.\n")

    code = _run(monkeypatch, [str(corpus), "-o", str(tmp_path / "out")])

    assert code == 0
    captured = capsys.readouterr()
    lines = captured.err.splitlines()
    assert lines == [
        f"  SKIP (legacy format): {corpus / 'old.xls'} -- legacy binary Excel "
        "format (.xls) is not supported. Save it as .xlsx and convert that file."
    ]
    # Other unsupported files in a scan stay quiet, as before.
    assert "notes.rtf" not in captured.err
    assert (tmp_path / "out" / "keep.md").exists()


def test_convert_file_reports_legacy_format(tmp_path, capsys):
    legacy = tmp_path / "deck.ppt"
    legacy.write_bytes(b"\xd0\xcf\x11\xe0legacy")

    assert convert_file(legacy, tmp_path / "out") is False
    assert "legacy binary PowerPoint format (.ppt) is not supported" in (
        capsys.readouterr().err
    )


def test_scanned_legacy_files_count_as_skips(monkeypatch, tmp_path, capsys):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "old.xls").write_bytes(b"\xd0\xcf\x11\xe0legacy")
    (corpus / "keep.txt").write_text("Plain notes.\n")

    code = _run(monkeypatch, [str(corpus), "-o", str(tmp_path / "out")])

    assert code == 0
    out = capsys.readouterr().out
    assert "Processing 2 file(s)" in out
    assert "1 converted, 1 skipped, 0 failed." in out


def test_folder_with_only_legacy_files_reports_the_skips(monkeypatch, tmp_path, capsys):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "old.xls").write_bytes(b"\xd0\xcf\x11\xe0legacy")
    (corpus / "deck.ppt").write_bytes(b"\xd0\xcf\x11\xe0legacy")

    code = _run(monkeypatch, [str(corpus), "-o", str(tmp_path / "out")])

    assert code == 0
    captured = capsys.readouterr()
    assert "No supported files to process." not in captured.out
    assert "0 converted, 2 skipped, 0 failed." in captured.out
    assert captured.err.count("SKIP (legacy format)") == 2


def test_legacy_file_seen_by_two_scans_counts_once(monkeypatch, tmp_path, capsys):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "old.xls").write_bytes(b"\xd0\xcf\x11\xe0legacy")

    _run(monkeypatch, [str(corpus), str(corpus), "-o", str(tmp_path / "out")])

    assert "0 converted, 1 skipped, 0 failed." in capsys.readouterr().out
