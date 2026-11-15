"""Unit tests for ``any2md.config``.

Covers ``.any2md.toml`` discovery (walking up from cwd), TOML loading,
and extraction of the two relevant sections: ``[meta]`` (frontmatter
overrides) and ``[document_id]`` (auto-id prefix / type code).
"""

from __future__ import annotations

import pytest

from any2md.config import (
    discover_config,
    extract_document_id_settings,
    extract_meta_overrides,
    load_toml,
)


def test_discover_config_finds_file(tmp_path):
    cfg = tmp_path / ".any2md.toml"
    cfg.write_text('[meta]\norganization = "X"\n')
    sub = tmp_path / "sub" / "deeper"
    sub.mkdir(parents=True)
    found = discover_config(start=sub)
    assert found == cfg


def test_discover_config_returns_none_when_absent(tmp_path):
    sub = tmp_path / "x"
    sub.mkdir()
    assert discover_config(start=sub) is None


def test_load_toml_roundtrip(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[meta]\norganization = "OWASP"\nauthors = ["Alice"]\n')
    cfg = load_toml(p)
    assert cfg["meta"]["organization"] == "OWASP"
    assert cfg["meta"]["authors"] == ["Alice"]


def test_extract_meta_overrides():
    cfg = {"meta": {"organization": "X"}, "other": {}}
    assert extract_meta_overrides(cfg) == {"organization": "X"}


def test_extract_document_id_settings_defaults():
    assert extract_document_id_settings({}) == ("LOCAL", "DOC")


def test_extract_document_id_settings_custom():
    cfg = {"document_id": {"publisher_prefix": "CSA", "type_code": "GD"}}
    assert extract_document_id_settings(cfg) == ("CSA", "GD")


def test_validate_document_id_settings_accepts_conforming_values():
    from any2md.config import validate_document_id_settings

    for prefix, type_code in [("LOCAL", "DOC"), ("CSA", "GD"), ("A1B2", "GUID")]:
        validate_document_id_settings(prefix, type_code)


@pytest.mark.parametrize(
    ("prefix", "type_code", "bad", "rule"),
    [
        ("csa", "GD", "'csa'", "^[A-Z0-9]+$"),
        ("", "GD", "''", "^[A-Z0-9]+$"),
        ("CS A", "GD", "'CS A'", "^[A-Z0-9]+$"),
        (123, "GD", "123", "^[A-Z0-9]+$"),
        ("CSA", "gd", "'gd'", "^[A-Z]{2,4}$"),
        ("CSA", "GUIDE", "'GUIDE'", "^[A-Z]{2,4}$"),
        ("CSA", "G1", "'G1'", "^[A-Z]{2,4}$"),
        ("CSA", "G", "'G'", "^[A-Z]{2,4}$"),
        ("CSA", "", "''", "^[A-Z]{2,4}$"),
    ],
)
def test_validate_document_id_settings_rejects(prefix, type_code, bad, rule):
    from any2md.config import validate_document_id_settings

    with pytest.raises(ValueError) as exc:
        validate_document_id_settings(prefix, type_code)
    msg = str(exc.value)
    assert bad in msg
    assert rule in msg
