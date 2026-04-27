"""Unit tests for any2md._http (URL validation + SSRF-safe fetcher)."""

from __future__ import annotations

import io
import socket
import urllib.error
from email.message import Message
from typing import Iterable

import pytest

from any2md._http import (
    _MAX_REDIRECT_HOPS,
    _MAX_RESPONSE_BYTES,
    safe_fetch,
    validate_url,
)


def _stub_dns(monkeypatch, mapping: dict[str, str]) -> None:
    """Make socket.getaddrinfo return mapping[host] for any lookup."""

    def fake(host, *args, **kwargs):
        ip = mapping.get(host, "1.1.1.1")  # default: a public IP
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0))]

    monkeypatch.setattr("any2md._http.socket.getaddrinfo", fake)


# ---------- validate_url ----------


@pytest.mark.parametrize(
    "ip,expect_disallowed",
    [
        ("127.0.0.1", True),
        ("10.0.0.1", True),
        ("192.168.1.1", True),
        ("169.254.169.254", True),  # AWS metadata
        ("::1", True),
        ("8.8.8.8", False),
        ("1.1.1.1", False),
    ],
)
def test_validate_url_ip_classification(monkeypatch, ip, expect_disallowed):
    _stub_dns(monkeypatch, {"x.example": ip})
    err = validate_url("https://x.example/")
    if expect_disallowed:
        assert err is not None and "disallowed" in err
    else:
        assert err is None


def test_validate_url_rejects_non_http_scheme(monkeypatch):
    err = validate_url("ftp://example.com/")
    assert err and "scheme" in err


def test_validate_url_rejects_file_scheme(monkeypatch):
    err = validate_url("file:///etc/passwd")
    assert err and "scheme" in err


def test_validate_url_no_hostname(monkeypatch):
    err = validate_url("http:///path-only")
    assert err and "hostname" in err


def test_validate_url_unresolvable(monkeypatch):
    def boom(*_a, **_kw):
        raise socket.gaierror("nodename nor servname provided")

    monkeypatch.setattr("any2md._http.socket.getaddrinfo", boom)
    err = validate_url("https://does-not-exist.invalid/")
    assert err and "resolve" in err


# ---------- safe_fetch redirect walking ----------


class _FakeHTTPResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None):
        self._body = body
        self._buf = io.BytesIO(body)
        msg = Message()
        for k, v in (headers or {}).items():
            msg[k] = v
        self.headers = msg

    def read(self, n: int | None = None) -> bytes:
        return self._buf.read(n) if n is not None else self._buf.read()


def _http_error(code: int, location: str | None = None) -> urllib.error.HTTPError:
    msg = Message()
    if location:
        msg["Location"] = location
    return urllib.error.HTTPError(url="x", code=code, msg="redirect", hdrs=msg, fp=None)


class _FakeOpener:
    def __init__(self, responses: Iterable):
        self.responses = list(responses)
        self.calls: list[str] = []

    def open(self, req, timeout):
        self.calls.append(req.full_url)
        r = self.responses.pop(0)
        if isinstance(r, urllib.error.HTTPError):
            raise r
        return r


def _patch_opener(monkeypatch, opener: _FakeOpener) -> None:
    monkeypatch.setattr("any2md._http.urllib.request.build_opener", lambda *_: opener)


def test_safe_fetch_simple_200(monkeypatch):
    _stub_dns(monkeypatch, {"public.example": "1.1.1.1"})
    opener = _FakeOpener([_FakeHTTPResponse(b"<html>ok</html>", {"X-Test": "1"})])
    _patch_opener(monkeypatch, opener)
    body, headers, err = safe_fetch("https://public.example/")
    assert err is None
    assert body == b"<html>ok</html>"
    assert headers and headers.get("X-Test") == "1"
    assert opener.calls == ["https://public.example/"]


def test_safe_fetch_follows_redirect_within_limit(monkeypatch):
    _stub_dns(monkeypatch, {"a.example": "1.1.1.1", "b.example": "2.2.2.2"})
    opener = _FakeOpener(
        [
            _http_error(302, "https://b.example/"),
            _FakeHTTPResponse(b"final"),
        ]
    )
    _patch_opener(monkeypatch, opener)
    body, _h, err = safe_fetch("https://a.example/")
    assert err is None
    assert body == b"final"
    assert opener.calls == ["https://a.example/", "https://b.example/"]


def test_safe_fetch_rejects_redirect_to_private(monkeypatch):
    _stub_dns(
        monkeypatch,
        {"a.example": "1.1.1.1", "rebound.example": "169.254.169.254"},
    )
    opener = _FakeOpener([_http_error(302, "https://rebound.example/")])
    _patch_opener(monkeypatch, opener)
    body, _h, err = safe_fetch("https://a.example/")
    assert body is None
    assert err and "disallowed" in err


def test_safe_fetch_max_hops(monkeypatch):
    _stub_dns(monkeypatch, {f"h{i}.example": "1.1.1.1" for i in range(10)})
    chain = [
        _http_error(302, f"https://h{i + 1}.example/")
        for i in range(_MAX_REDIRECT_HOPS + 2)
    ]
    opener = _FakeOpener(chain)
    _patch_opener(monkeypatch, opener)
    _b, _h, err = safe_fetch("https://h0.example/")
    assert err and "too many redirects" in err.lower()


def test_safe_fetch_loop_detection(monkeypatch):
    _stub_dns(monkeypatch, {"loop.example": "1.1.1.1"})
    opener = _FakeOpener([_http_error(302, "https://loop.example/")])
    _patch_opener(monkeypatch, opener)
    _b, _h, err = safe_fetch("https://loop.example/")
    assert err and "loop" in err.lower()


def test_safe_fetch_response_size_cap(monkeypatch):
    _stub_dns(monkeypatch, {"big.example": "1.1.1.1"})
    huge = b"x" * (_MAX_RESPONSE_BYTES + 100)
    opener = _FakeOpener([_FakeHTTPResponse(huge)])
    _patch_opener(monkeypatch, opener)
    _b, _h, err = safe_fetch("https://big.example/")
    assert err and "exceeds" in err


def test_safe_fetch_head_method(monkeypatch):
    _stub_dns(monkeypatch, {"head.example": "1.1.1.1"})
    opener = _FakeOpener(
        [_FakeHTTPResponse(b"", {"Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT"})]
    )
    _patch_opener(monkeypatch, opener)
    _b, headers, err = safe_fetch("https://head.example/", method="HEAD")
    assert err is None
    assert headers and headers.get("Last-Modified")


def test_safe_fetch_http_error_other(monkeypatch):
    _stub_dns(monkeypatch, {"err.example": "1.1.1.1"})
    opener = _FakeOpener([_http_error(500)])
    _patch_opener(monkeypatch, opener)
    _b, _h, err = safe_fetch("https://err.example/")
    assert err and "500" in err
