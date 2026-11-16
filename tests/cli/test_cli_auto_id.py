"""End-to-end tests for the CLI ``--auto-id`` flag.

Every generated ``document_id`` must match the SAGE v1.0-RC1 rule, take
its year from the emitted ``date`` field, yield to an explicit
``--meta document_id=...``, and refuse a non-conforming
``publisher_prefix`` or ``type_code`` with exit code 1.
"""

from __future__ import annotations

import re
import subprocess
import sys

import pytest
import yaml

SAGE_ID_RE = re.compile(r"^[A-Z0-9]+-\d{4}-[A-Z]{2,4}-\d{3,}$")
_FIXTURE = "ligatures_and_softhyphens.txt"


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "any2md", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def _frontmatter(path) -> dict:
    md = path.read_text()
    end = md.index("\n---\n", 4)
    return yaml.safe_load(md[4:end])


def _project(tmp_path, toml: str | None = None):
    """A project dir with a boundary marker so discovery stops there."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".any2md.toml.boundary").write_text("")
    if toml is not None:
        (proj / ".any2md.toml").write_text(toml)
    return proj


def test_auto_id_default_settings_conform(fixture_dir, tmp_path):
    out = tmp_path / "out"
    r = _run("-o", str(out), "--no-config", "--auto-id", str(fixture_dir / _FIXTURE))
    assert r.returncode == 0, r.stderr
    doc_id = _frontmatter(out / "ligatures_and_softhyphens.md")["document_id"]
    assert SAGE_ID_RE.match(doc_id), doc_id
    assert doc_id.startswith("LOCAL-")
    assert "-DOC-" in doc_id


def test_auto_id_configured_prefix_conforms(fixture_dir, tmp_path):
    proj = _project(
        tmp_path, '[document_id]\npublisher_prefix = "CSA"\ntype_code = "GD"\n'
    )
    out = tmp_path / "out"
    r = _run("-o", str(out), "--auto-id", str(fixture_dir / _FIXTURE), cwd=proj)
    assert r.returncode == 0, r.stderr
    doc_id = _frontmatter(out / "ligatures_and_softhyphens.md")["document_id"]
    assert SAGE_ID_RE.match(doc_id), doc_id
    assert doc_id.startswith("CSA-")
    assert "-GD-" in doc_id


def test_auto_id_year_follows_meta_date(fixture_dir, tmp_path):
    out = tmp_path / "out"
    r = _run(
        "-o",
        str(out),
        "--no-config",
        "--auto-id",
        "--meta",
        "date=2015-07-08",
        str(fixture_dir / _FIXTURE),
    )
    assert r.returncode == 0, r.stderr
    fm = _frontmatter(out / "ligatures_and_softhyphens.md")
    assert fm["date"] == "2015-07-08"
    assert fm["document_id"].split("-")[1] == "2015"


def test_explicit_meta_document_id_overrides_auto_id(fixture_dir, tmp_path):
    out = tmp_path / "out"
    r = _run(
        "-o",
        str(out),
        "--no-config",
        "--auto-id",
        "--meta",
        "document_id=OWASP-2025-GD-001",
        str(fixture_dir / _FIXTURE),
    )
    assert r.returncode == 0, r.stderr
    fm = _frontmatter(out / "ligatures_and_softhyphens.md")
    assert fm["document_id"] == "OWASP-2025-GD-001"


@pytest.mark.parametrize(
    ("section", "bad", "rule"),
    [
        ('publisher_prefix = "csa"', "'csa'", "^[A-Z0-9]+$"),
        ('publisher_prefix = ""', "''", "^[A-Z0-9]+$"),
        ('type_code = "gd"', "'gd'", "^[A-Z]{2,4}$"),
        ('type_code = "GUIDE"', "'GUIDE'", "^[A-Z]{2,4}$"),
        ('type_code = "G1"', "'G1'", "^[A-Z]{2,4}$"),
        ('type_code = ""', "''", "^[A-Z]{2,4}$"),
    ],
)
def test_invalid_id_settings_exit_1(fixture_dir, tmp_path, section, bad, rule):
    proj = _project(tmp_path, f"[document_id]\n{section}\n")
    out = tmp_path / "out"
    r = _run("-o", str(out), "--auto-id", str(fixture_dir / _FIXTURE), cwd=proj)
    assert r.returncode == 1, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert bad in r.stderr
    assert rule in r.stderr
    assert not out.exists() or not any(out.iterdir())


def test_invalid_id_settings_in_meta_file_exit_1(fixture_dir, tmp_path):
    meta_file = tmp_path / "meta.toml"
    meta_file.write_text('[document_id]\ntype_code = "DOCUMENT"\n')
    out = tmp_path / "out"
    r = _run(
        "-o",
        str(out),
        "--no-config",
        "--auto-id",
        "--meta-file",
        str(meta_file),
        str(fixture_dir / _FIXTURE),
    )
    assert r.returncode == 1, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "'DOCUMENT'" in r.stderr


def test_invalid_id_settings_ignored_without_auto_id(fixture_dir, tmp_path):
    """A run that never generates an id is not blocked by unused settings."""
    proj = _project(tmp_path, '[document_id]\npublisher_prefix = "csa"\n')
    out = tmp_path / "out"
    r = _run("-o", str(out), str(fixture_dir / _FIXTURE), cwd=proj)
    assert r.returncode == 0, r.stderr


def test_invalid_id_settings_ignored_when_meta_document_id_wins(fixture_dir, tmp_path):
    """No id is generated, so a bad unused prefix must not exit 1."""
    proj = _project(tmp_path, '[document_id]\npublisher_prefix = "CoSAI"\n')
    out = tmp_path / "out"
    r = _run(
        "-o",
        str(out),
        "--auto-id",
        "--meta",
        "document_id=COSAI-2025-GD-001",
        str(fixture_dir / _FIXTURE),
        cwd=proj,
    )
    assert r.returncode == 0, r.stderr
    fm = _frontmatter(out / "ligatures_and_softhyphens.md")
    assert fm["document_id"] == "COSAI-2025-GD-001"


def test_bad_date_override_exits_1_before_conversion(fixture_dir, tmp_path):
    out = tmp_path / "out"
    r = _run(
        "-o",
        str(out),
        "--no-config",
        "--auto-id",
        "--meta",
        "date=2025/03/01",
        str(fixture_dir / _FIXTURE),
    )
    assert r.returncode == 1, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "'2025/03/01'" in r.stderr
    assert not out.exists() or not any(out.iterdir())


def test_blank_meta_document_id_still_validates_settings(fixture_dir, tmp_path):
    """document_id=, parses to [] and must not count as an explicit id."""
    proj = _project(tmp_path, '[document_id]\npublisher_prefix = "CoSAI"\n')
    out = tmp_path / "out"
    r = _run(
        "-o",
        str(out),
        "--auto-id",
        "--meta",
        "document_id=,",
        str(fixture_dir / _FIXTURE),
        cwd=proj,
    )
    assert r.returncode == 1, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "'CoSAI'" in r.stderr


def _docx_with_modified(src, dst, modified: str) -> None:
    """Copy a DOCX fixture with dcterms:modified replaced."""
    import re as _re
    import zipfile

    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "docProps/core.xml":
                text = data.decode("utf-8")
                # Replace only the element text, so its inline namespace
                # declarations survive and core.xml still parses.
                text, n = _re.subn(
                    r"(<dcterms:modified[^>]*>).*?(</dcterms:modified>)",
                    lambda m: m.group(1) + modified + m.group(2),
                    text,
                    flags=_re.S,
                )
                assert n == 1
                data = text.encode("utf-8")
            zout.writestr(item, data)


def _pdf_with_creation_date(dst, creation_date: str) -> None:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Report body text for the dropped date test.")
    doc.set_metadata({"creationDate": creation_date})
    doc.save(dst)
    doc.close()


def test_dropped_docx_date_warns_once(fixture_dir, tmp_path):
    src = tmp_path / "pretty.docx"
    _docx_with_modified(fixture_dir / "table_heavy.docx", src, "2019-06")
    r = _run("-o", str(tmp_path / "out"), "--no-config", "--auto-id", str(src))
    assert r.returncode == 0, r.stderr
    assert r.stderr.count("ignoring document date '2019-06'") == 1, r.stderr
    assert "modification time" in r.stderr


def test_dropped_pdf_date_warns_once(tmp_path):
    src = tmp_path / "zeroed.pdf"
    _pdf_with_creation_date(src, "D:00000000000000")
    r = _run("-o", str(tmp_path / "out"), "--no-config", "--auto-id", str(src))
    assert r.returncode == 0, r.stderr
    assert r.stderr.count("ignoring document date 'D:00000000000000'") == 1, r.stderr


def test_date_override_silences_dropped_date_warning(tmp_path):
    src = tmp_path / "zeroed.pdf"
    _pdf_with_creation_date(src, "D:00000000000000")
    out = tmp_path / "out"
    r = _run(
        "-o",
        str(out),
        "--no-config",
        "--auto-id",
        "--meta",
        "date=2025-03-01",
        str(src),
    )
    assert r.returncode == 0, r.stderr
    assert "ignoring document date" not in r.stderr
    fm = _frontmatter(out / "zeroed.md")
    assert fm["date"] == "2025-03-01"
    assert fm["document_id"].split("-")[1] == "2025"


@pytest.mark.parametrize("bad", ["2025-13-99", "2025", "2025-3"])
def test_non_calendar_date_override_exits_1(fixture_dir, tmp_path, bad):
    r = _run(
        "-o",
        str(tmp_path / "out"),
        "--no-config",
        "--auto-id",
        "--meta",
        f"date={bad}",
        str(fixture_dir / _FIXTURE),
    )
    assert r.returncode == 1, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert f"'{bad}'" in r.stderr
    assert "YYYY-MM-DD" in r.stderr


def test_iso_datetime_override_is_accepted_and_normalized(fixture_dir, tmp_path):
    out = tmp_path / "out"
    r = _run(
        "-o",
        str(out),
        "--no-config",
        "--auto-id",
        "--meta",
        "date=2025-03-01T10:00:00Z",
        str(fixture_dir / _FIXTURE),
    )
    assert r.returncode == 0, r.stderr
    fm = _frontmatter(out / "ligatures_and_softhyphens.md")
    assert fm["date"] == "2025-03-01"
    assert fm["document_id"].split("-")[1] == "2025"
