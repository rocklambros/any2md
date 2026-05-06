"""Locked error strings — v1.1.1 public CLI contract.

Each entry in LOCKED_ERROR_STRINGS pairs a code path with a substring
that MUST appear in the user-visible output. Changing a string requires
updating this test AND adding a CHANGELOG ### Changed entry.
"""

from __future__ import annotations

import os
import socket
import sys

import pytest

LOCKED_ERROR_STRINGS = {
    "ssrf_disallowed": "URL resolves to disallowed address: ",
    "ssrf_scheme": "scheme",
    "ssrf_no_hostname": "no hostname in URL",
    "url_creds": "stripped credentials from URL",
    "url_query": "stripped sensitive query parameter",
    "toml_warn": "failed to parse",
    "symlink_refuse": "refusing to write through symlink",
}


def _gai(ip: str):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 0, "", (ip, 0))]


def test_ssrf_disallowed_address_string(monkeypatch):
    from any2md._http import safe_fetch

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: _gai("169.254.169.254"))
    body, headers, err = safe_fetch("https://example.com/")
    assert err is not None
    assert LOCKED_ERROR_STRINGS["ssrf_disallowed"] in err
    assert "169.254.169.254" in err


def test_ssrf_scheme_string():
    from any2md._http import safe_fetch

    body, headers, err = safe_fetch("file:///etc/passwd")
    assert err is not None
    assert LOCKED_ERROR_STRINGS["ssrf_scheme"] in err.lower()


def test_url_creds_warning_string(capsys):
    from any2md._logging import warn

    warn("stripped credentials from URL")
    assert LOCKED_ERROR_STRINGS["url_creds"] in capsys.readouterr().err


def test_url_query_warning_string(capsys):
    from any2md._logging import warn

    warn("stripped sensitive query parameter 'api_key' from URL")
    assert LOCKED_ERROR_STRINGS["url_query"] in capsys.readouterr().err


def test_toml_warn_string(tmp_path, capsys):
    from any2md.config import load_toml

    bad = tmp_path / ".any2md.toml"
    bad.write_text("garbage = = =")
    load_toml(bad)
    assert LOCKED_ERROR_STRINGS["toml_warn"] in capsys.readouterr().err


def test_symlink_refuse_string(tmp_path):
    if sys.platform == "win32":
        pytest.skip("symlinks POSIX-only")

    from any2md.utils import atomic_write_text

    sentinel = tmp_path / "sentinel"
    sentinel.write_text("safe")
    target = tmp_path / "out.md"
    os.symlink(sentinel, target)

    with pytest.raises(ValueError) as exc_info:
        atomic_write_text(target, "evil")
    assert LOCKED_ERROR_STRINGS["symlink_refuse"] in str(exc_info.value)
