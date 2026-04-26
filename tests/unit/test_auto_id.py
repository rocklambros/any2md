"""Unit tests for ``frontmatter.generate_document_id``.

The id pattern is ``{PREFIX}-{YYYY}-{TYPE}-{SHA8}``. The SHA8 is the
first 8 hex chars of the body's content hash (NFC + LF SHA-256), so
two bodies that share a ``content_hash`` share an ``id``.
"""

from __future__ import annotations

from datetime import date

from any2md.frontmatter import generate_document_id


def test_generate_document_id_format():
    body = "# Title\n\nbody.\n"
    doc_id = generate_document_id(body, prefix="LOCAL", type_code="DOC")
    parts = doc_id.split("-")
    assert len(parts) == 4
    assert parts[0] == "LOCAL"
    assert parts[1] == str(date.today().year)
    assert parts[2] == "DOC"
    assert len(parts[3]) == 8
    assert all(c in "0123456789abcdef" for c in parts[3])


def test_document_id_deterministic():
    body = "# Title\n\nbody.\n"
    a = generate_document_id(body)
    b = generate_document_id(body)
    assert a == b


def test_document_id_changes_with_body():
    a = generate_document_id("body one")
    b = generate_document_id("body two")
    assert a != b


def test_custom_prefix_and_type_code():
    body = "x"
    doc_id = generate_document_id(body, prefix="CSA", type_code="GD")
    assert doc_id.startswith("CSA-")
    assert "-GD-" in doc_id


def test_auto_id_uses_config_prefix(tmp_path, monkeypatch):
    """``.any2md.toml`` ``[document_id]`` settings drive --auto-id."""
    cfg = tmp_path / ".any2md.toml"
    cfg.write_text(
        '[document_id]\npublisher_prefix = "CSA"\ntype_code = "GD"\n'
    )
    monkeypatch.chdir(tmp_path)
    from any2md.config import (
        discover_config,
        extract_document_id_settings,
        load_toml,
    )

    discovered = discover_config()
    assert discovered == cfg
    p, t = extract_document_id_settings(load_toml(discovered))
    assert p == "CSA"
    assert t == "GD"
