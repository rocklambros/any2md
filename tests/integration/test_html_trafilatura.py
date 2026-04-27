"""Integration test: HTML converter end-to-end."""

import yaml

from any2md.converters.html import convert_html
from any2md.pipeline import PipelineOptions


def test_html_local_file_emits_v1_frontmatter(fixture_dir, tmp_output_dir):
    ok = convert_html(
        fixture_dir / "web_page.html",
        tmp_output_dir,
        options=PipelineOptions(),
        force=True,
    )
    assert ok
    out_files = list(tmp_output_dir.glob("*.md"))
    assert len(out_files) == 1
    out = out_files[0].read_text(encoding="utf-8")
    end = out.index("\n---\n", 4)
    fm = yaml.safe_load(out[4:end])
    body = out[end + 5 :]
    assert fm["status"] == "draft"
    assert "trafilatura" in fm["extracted_via"]
    # boilerplate stripped
    assert "Sidebar noise" not in body
    assert "Site footer" not in body
    # body content present
    assert "Test Article" in fm["title"] or "Test Article" in body


# ---------- SSRF integration tests (v1.0.6 / F1) ----------

import socket
import urllib.error
from email.message import Message
from io import BytesIO

import any2md.converters.html as html_mod


class _FakeResp:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None):
        self._buf = BytesIO(body)
        m = Message()
        for k, v in (headers or {}).items():
            m[k] = v
        self.headers = m

    def read(self, n: int | None = None) -> bytes:
        return self._buf.read(n) if n is not None else self._buf.read()


def _http_err(code: int, location: str | None = None):
    m = Message()
    if location:
        m["Location"] = location
    return urllib.error.HTTPError("x", code, "redir", m, None)


class _FakeOpener:
    def __init__(self, seq):
        self.seq = list(seq)
        self.calls = []

    def open(self, req, timeout):
        self.calls.append(req.full_url)
        r = self.seq.pop(0)
        if isinstance(r, urllib.error.HTTPError):
            raise r
        return r


def _stub_dns(monkeypatch, mapping):
    def fake(host, *_a, **_kw):
        ip = mapping.get(host, "1.1.1.1")
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0))]

    monkeypatch.setattr("any2md._http.socket.getaddrinfo", fake)


def _patch_opener(monkeypatch, opener):
    monkeypatch.setattr(
        "any2md._http.urllib.request.build_opener", lambda *_: opener
    )


def test_fetch_url_rejects_redirect_to_metadata_endpoint(monkeypatch):
    _stub_dns(
        monkeypatch,
        {"public.example": "1.1.1.1", "rebound.example": "169.254.169.254"},
    )
    opener = _FakeOpener([_http_err(302, "http://rebound.example/")])
    _patch_opener(monkeypatch, opener)
    body, err = html_mod.fetch_url("https://public.example/")
    assert body is None
    assert err and "disallowed" in err


def test_fetch_url_rejects_file_scheme(monkeypatch):
    body, err = html_mod.fetch_url("file:///etc/passwd")
    assert body is None
    assert err and "scheme" in err


def test_http_last_modified_validates_host(monkeypatch):
    _stub_dns(monkeypatch, {"meta.example": "169.254.169.254"})
    assert html_mod._http_last_modified("http://meta.example/") is None
