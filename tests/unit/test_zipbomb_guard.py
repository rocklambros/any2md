"""Tests for _safe_zip_open in any2md/converters/docx.py (F4)."""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

import pytest

from any2md.converters.docx import _MAX_DOCX_METADATA_SIZE, _safe_zip_open


def _make_zip_with_lying_size(out: Path, member: str, declared_size: int):
    """Build a zip whose ``member`` declares ``declared_size`` uncompressed.

    We write a small real body, then mutate the central directory's
    uncompressed-size field so ``ZipInfo.file_size`` reports the lie.
    """
    real_body = b"<x/>"
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(member, real_body)
    raw = out.read_bytes()
    # Central directory entry signature is PK\x01\x02; uncompressed-size
    # is at offset +24 (4 bytes, little-endian).
    sig = b"PK\x01\x02"
    idx = raw.find(sig)
    assert idx != -1
    raw = raw[: idx + 24] + struct.pack("<I", declared_size) + raw[idx + 28 :]
    out.write_bytes(raw)


def test_safe_zip_open_accepts_normal(tmp_path):
    z = tmp_path / "ok.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.xml", b"<x/>")
    with zipfile.ZipFile(z) as zf:
        f = _safe_zip_open(zf, "a.xml")
        assert f.read() == b"<x/>"


def test_safe_zip_open_rejects_oversized(tmp_path):
    z = tmp_path / "bomb.zip"
    _make_zip_with_lying_size(z, "core.xml", _MAX_DOCX_METADATA_SIZE + 1)
    with zipfile.ZipFile(z) as zf:
        with pytest.raises(ValueError, match="exceeds"):
            _safe_zip_open(zf, "core.xml")
