"""DOCX image links must never make mammoth read files or URLs.

A DOCX can reference an image by link (``a:blip r:link``) instead of
embedding it. mammoth releases before 1.11.0 open such a link with
``urlopen`` or ``open``, which reads local files and reaches internal
hosts outside the SSRF guard (CVE-2025-11849).
"""

from __future__ import annotations

import base64
import zipfile
from pathlib import Path

import mammoth
import mammoth.docx.files
import pytest

import any2md.converters.docx as docx_mod
from any2md.pipeline import PipelineOptions

_SECRET = b"TOP-SECRET-KEY-MATERIAL-0123456789"

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{target}" TargetMode="External"/>
</Relationships>
"""

_DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
  xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    <w:p><w:r><w:t>Before image.</w:t></w:r></w:p>
    <w:p><w:r><w:drawing><wp:inline>
      <wp:docPr id="1" name="Picture 1" descr="linked"/>
      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
        <pic:pic><pic:blipFill><a:blip r:link="rId9"/></pic:blipFill></pic:pic>
      </a:graphicData></a:graphic>
    </wp:inline></w:drawing></w:r></w:p>
  </w:body>
</w:document>
"""


def _build_docx(path: Path, target: str) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS.format(target=target))
        z.writestr("word/document.xml", _DOCUMENT)


@pytest.fixture
def secret_docx(tmp_path):
    """A DOCX whose image links to a sibling file holding a secret."""
    (tmp_path / "secret.png").write_bytes(_SECRET)
    docx_path = tmp_path / "evil.docx"
    _build_docx(docx_path, "secret.png")
    return docx_path


def _assert_no_secret(md: str) -> None:
    assert _SECRET.decode() not in md
    assert base64.b64encode(_SECRET).decode() not in md


def test_fixture_reaches_external_file_when_access_is_enabled(secret_docx):
    """Guards the fixture: with access turned on, mammoth does read the
    linked file. Without this, the tests below could pass vacuously."""
    with open(secret_docx, "rb") as f:
        html = mammoth.convert_to_html(f, external_file_access=True).value
    assert base64.b64encode(_SECRET).decode() in html


@pytest.mark.parametrize("save_images", [True, False])
def test_mammoth_lane_disables_external_file_access(
    secret_docx, save_images, monkeypatch
):
    seen: dict = {}
    real = mammoth.convert_to_html

    def spy(fileobj, **kwargs):
        seen.update(kwargs)
        return real(fileobj, **kwargs)

    monkeypatch.setattr(docx_mod.mammoth, "convert_to_html", spy)
    md, _ = docx_mod._extract_via_mammoth(
        secret_docx, PipelineOptions(save_images=save_images)
    )
    assert seen.get("external_file_access") is False
    _assert_no_secret(md)


@pytest.mark.parametrize("save_images", [True, False])
def test_old_mammoth_never_opens_images(secret_docx, save_images, monkeypatch):
    """On a mammoth without the external-access switch, any2md must not
    open any image, since mammoth's image object does not say whether
    an image is linked or embedded."""
    opened: list[str] = []

    def leaky_open(self, uri):
        # Behave like mammoth before 1.11.0: no access check at all.
        opened.append(uri)
        return open(Path(self._base) / uri, "rb")

    monkeypatch.setattr(mammoth.docx.files.Files, "open", leaky_open)
    monkeypatch.setattr(docx_mod, "_mammoth_blocks_external_files", lambda: False)
    md, _ = docx_mod._extract_via_mammoth(
        secret_docx, PipelineOptions(save_images=save_images)
    )
    assert opened == []
    _assert_no_secret(md)


@pytest.mark.parametrize(
    "version, expected",
    [
        ("1.6.0", False),
        ("1.10.9", False),
        ("1.11.0", True),
        ("1.12.0", True),
        ("2.0.0", True),
        ("not-a-version", False),
    ],
)
def test_mammoth_version_gate(version, expected, monkeypatch):
    monkeypatch.setattr(docx_mod, "_installed_mammoth_version", lambda: version)
    assert docx_mod._mammoth_blocks_external_files() is expected


# An embedded image lives inside the DOCX zip (``a:blip r:embed``). Its
# marker bytes show up base64-encoded in mammoth's HTML only when mammoth
# reads them, which lets the tests below tell skipped reads from real ones.
_EMBEDDED_BYTES = b"EMBEDDED-IMAGE-MARKER-BYTES-9876543210"

_EMBED_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId10" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>
</Relationships>
"""


@pytest.fixture
def embedded_docx(tmp_path):
    """A DOCX that embeds its image in the package, with no links."""
    docx_path = tmp_path / "embedded.docx"
    document = _DOCUMENT.replace('descr="linked"', 'descr="embedded"').replace(
        'r:link="rId9"', 'r:embed="rId10"'
    )
    with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels", _EMBED_RELS)
        z.writestr("word/document.xml", document)
        z.writestr("word/media/image1.png", _EMBEDDED_BYTES)
    return docx_path


def _mammoth_html(monkeypatch, docx_path: Path, save_images: bool) -> tuple[str, str]:
    """Run the mammoth lane and return (mammoth HTML, markdown)."""
    seen: list[str] = []
    real = mammoth.convert_to_html

    def spy(fileobj, **kwargs):
        result = real(fileobj, **kwargs)
        seen.append(result.value)
        return result

    monkeypatch.setattr(docx_mod.mammoth, "convert_to_html", spy)
    md, _ = docx_mod._extract_via_mammoth(
        docx_path, PipelineOptions(save_images=save_images)
    )
    return seen[0], md


def test_embedded_image_bytes_not_read_without_save_images(embedded_docx, monkeypatch):
    if not docx_mod._mammoth_blocks_external_files():
        pytest.skip("covers the safe-mammoth branch")
    html, md = _mammoth_html(monkeypatch, embedded_docx, save_images=False)
    marker = base64.b64encode(_EMBEDDED_BYTES).decode()
    # Without the skip converter, mammoth inlines the bytes as a data URI.
    assert marker not in html
    assert marker not in md
    assert "Before image." in md


def test_embedded_image_kept_with_save_images(embedded_docx, monkeypatch):
    if not docx_mod._mammoth_blocks_external_files():
        pytest.skip("covers the safe-mammoth branch")
    html, md = _mammoth_html(monkeypatch, embedded_docx, save_images=True)
    marker = base64.b64encode(_EMBEDDED_BYTES).decode()
    assert marker in html
    assert marker in md
