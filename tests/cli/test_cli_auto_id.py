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
