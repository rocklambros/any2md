"""Test the IP allowlist (is_global + not multicast/unspecified)."""

from __future__ import annotations

import socket

import pytest

from any2md._http import validate_url


def _gai_result(ip: str):
    """Build a getaddrinfo() return value for a single IP."""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 0, "", (ip, 0))]


@pytest.mark.parametrize(
    "ip, allowed",
    [
        ("8.8.8.8", True),
        ("1.1.1.1", True),
        ("169.254.169.254", False),  # link-local (AWS metadata)
        ("10.0.0.1", False),          # RFC1918
        ("172.16.0.1", False),        # RFC1918
        ("192.168.1.1", False),       # RFC1918
        ("127.0.0.1", False),         # loopback
        ("0.0.0.0", False),           # unspecified
        ("224.0.0.1", False),         # IPv4 multicast
        ("100.64.0.1", False),        # CGNAT
        ("192.0.0.1", False),         # IETF reserved
        ("::1", False),               # IPv6 loopback
        ("ff02::1", False),           # IPv6 multicast
        ("fe80::1", False),           # IPv6 link-local
    ],
)
def test_validate_url_ip_allowlist(ip, allowed, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: _gai_result(ip))
    err = validate_url("https://example.com/")
    if allowed:
        assert err is None, f"expected {ip} to be allowed but got: {err}"
    else:
        assert err is not None and "disallowed" in err
        assert ip in err  # error includes the offending IP


def test_validate_url_rejects_multi_record_if_any_bad(monkeypatch):
    """If any A record is private, reject (deny-on-any)."""
    def gai(*a, **kw):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 0)),
        ]
    monkeypatch.setattr(socket, "getaddrinfo", gai)
    err = validate_url("https://example.com/")
    assert err is not None and "disallowed" in err


def test_validate_url_rejects_unsupported_scheme():
    err = validate_url("file:///etc/passwd")
    assert err is not None and "scheme" in err.lower()


def test_validate_url_rejects_no_hostname():
    err = validate_url("http:///nopath")
    assert err is not None
