"""Test the SSRF intra-hop DNS-rebind defense (IP-pinned connector + ProxyHandler)."""

from __future__ import annotations

import socket


def _gai(ip: str):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 0, "", (ip, 0))]


def test_safe_fetch_ignores_https_proxy_env(monkeypatch):
    """Even with HTTPS_PROXY set, our pinned opener bypasses the env proxy."""
    from any2md import _http

    monkeypatch.setenv("HTTPS_PROXY", "http://attacker:8888")
    monkeypatch.setenv("HTTP_PROXY", "http://attacker:8888")

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: _gai("8.8.8.8"))

    captured = {}

    def fake_create_connection(addr, timeout=None):
        captured["addr"] = addr
        raise OSError("simulated refusal")

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)

    body, headers, err = _http.safe_fetch("https://example.com/")
    assert err is not None  # connection simulated as refused
    assert captured.get("addr") == ("8.8.8.8", 443), (
        f"pinned opener should connect to validated IP, got {captured.get('addr')!r}"
    )


def test_safe_fetch_uses_pinned_ip_not_secondary_resolution(monkeypatch):
    """getaddrinfo returns 8.8.8.8 first, then 127.0.0.1 on subsequent
    calls — connection must use 8.8.8.8 (the validated one)."""
    from any2md import _http

    call_count = [0]

    def staged_gai(*a, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return _gai("8.8.8.8")
        return _gai("127.0.0.1")

    monkeypatch.setattr(socket, "getaddrinfo", staged_gai)

    captured = {}

    def fake_create_connection(addr, timeout=None):
        captured["addr"] = addr
        raise OSError("simulated")

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)

    _http.safe_fetch("https://example.com/")
    assert captured["addr"] == ("8.8.8.8", 443), (
        f"pinned IP should be 8.8.8.8 (first resolution), got {captured.get('addr')!r}"
    )
