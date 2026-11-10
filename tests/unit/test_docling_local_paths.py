"""Local files must reach Docling as Path objects, never as str.

Docling runs every str source through ``resolve_source_to_stream``,
which tries it as an HTTP URL first. A file named
``http:attacker.example#.docx`` would then be fetched from the network
instead of read from disk. Path sources skip URL resolution.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

import any2md._docling_cache as cache_mod
import any2md.converters.docx as docx_mod
import any2md.converters.pdf as pdf_mod
from any2md.pipeline import PipelineOptions

_HOSTILE_NAMES = ["http:attacker.example#.{ext}", "https:evil.example#.{ext}"]


class _FakeResult:
    class document:  # noqa: N801  mimics Docling's attribute shape
        pictures: list = []

        @staticmethod
        def export_to_markdown() -> str:
            return "# Title\n\nBody.\n"


class _RecordingConverter:
    def __init__(self) -> None:
        self.sources: list = []

    def convert(self, source):
        self.sources.append(source)
        return _FakeResult()


@pytest.fixture
def fake_docling_options(monkeypatch):
    """pdf.py imports PdfPipelineOptions from Docling at call time."""
    pkg = types.ModuleType("docling")
    datamodel = types.ModuleType("docling.datamodel")
    pipeline_options = types.ModuleType("docling.datamodel.pipeline_options")
    pipeline_options.PdfPipelineOptions = types.SimpleNamespace
    monkeypatch.setitem(sys.modules, "docling", pkg)
    monkeypatch.setitem(sys.modules, "docling.datamodel", datamodel)
    monkeypatch.setitem(
        sys.modules, "docling.datamodel.pipeline_options", pipeline_options
    )


@pytest.mark.parametrize("template", _HOSTILE_NAMES)
def test_docx_docling_receives_path(template, tmp_path, monkeypatch):
    conv = _RecordingConverter()
    monkeypatch.setattr(cache_mod, "get_docx_converter", lambda: conv)
    monkeypatch.chdir(tmp_path)
    rel = Path(template.format(ext="docx"))
    rel.write_bytes(b"not used")

    docx_mod._extract_via_docling(rel)

    assert len(conv.sources) == 1
    assert isinstance(conv.sources[0], Path)
    assert conv.sources[0] == rel


@pytest.mark.parametrize("template", _HOSTILE_NAMES)
def test_pdf_docling_receives_path(
    template, tmp_path, monkeypatch, fake_docling_options
):
    conv = _RecordingConverter()
    monkeypatch.setattr(cache_mod, "get_pdf_converter", lambda opts: conv)
    monkeypatch.chdir(tmp_path)
    rel = Path(template.format(ext="pdf"))
    rel.write_bytes(b"not used")

    pdf_mod._extract_via_docling(rel, PipelineOptions(), tmp_path / "out")

    assert len(conv.sources) == 1
    assert isinstance(conv.sources[0], Path)
    assert conv.sources[0] == rel
