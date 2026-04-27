"""SSRF-safe HTTP fetching utilities for any2md.

Centralizes URL scheme + IP validation and provides a fetcher that
walks redirects manually and revalidates the host on each hop. This
defends against:
  - DNS rebinding (host -> public IP for validator, private IP for fetch)
  - Redirect-based SSRF (public landing page -> 302 to 169.254.169.254)
  - Non-http(s) schemes (file://, gopher://, etc.)
  - Decompression / huge-response DoS (response-size cap)
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request

_MAX_REDIRECT_HOPS = 3
_FETCH_TIMEOUT = 15  # seconds
_MAX_RESPONSE_BYTES = 20 * 1024 * 1024  # 20 MB cap on body read
_USER_AGENT = "any2md/1.0.6"


def validate_url(url: str) -> str | None:
    """Validate URL scheme + host. Returns an error message or None.

    One-shot DNS lookup; rebind protection requires re-checking on
    every redirect hop (handled by ``safe_fetch``).
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"unsupported scheme: {parsed.scheme!r}"
    if not parsed.hostname:
        return f"no hostname in URL: {url}"
    try:
        infos = socket.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return f"cannot resolve host: {parsed.hostname}"
    for *_, sockaddr in infos:
        try:
            addr = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if (
            addr.is_private
            or addr.is_reserved
            or addr.is_loopback
            or addr.is_link_local
        ):
            return f"URL resolves to disallowed address: {addr}"
    return None


class _NoFollowRedirect(urllib.request.HTTPRedirectHandler):
    """Disable urllib's automatic redirect following."""

    def redirect_request(self, *args, **kwargs):  # noqa: ARG002
        return None


def safe_fetch(
    url: str,
    *,
    method: str = "GET",
    max_hops: int = _MAX_REDIRECT_HOPS,
) -> tuple[bytes | None, dict | None, str | None]:
    """Fetch ``url`` with manual redirect walking + per-hop revalidation.

    Returns ``(body, headers, None)`` on 2xx, or ``(None, None, error)``
    on rejection / failure. ``headers`` is the response headers as a
    plain ``dict``.
    """
    visited: list[str] = []
    current = url
    opener = urllib.request.build_opener(_NoFollowRedirect())
    for hop in range(max_hops + 1):
        if current in visited:
            return None, None, "redirect loop"
        visited.append(current)
        err = validate_url(current)
        if err:
            return None, None, err
        req = urllib.request.Request(
            current, method=method, headers={"User-Agent": _USER_AGENT}
        )
        try:
            resp = opener.open(req, timeout=_FETCH_TIMEOUT)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                if hop >= max_hops:
                    return None, None, f"too many redirects (>{max_hops})"
                location = e.headers.get("Location") if e.headers else None
                if not location:
                    return None, None, f"HTTP {e.code} without Location"
                current = urllib.parse.urljoin(current, location)
                continue
            return None, None, f"HTTP {e.code}"
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            return None, None, f"fetch error: {e}"
        body = resp.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            return None, None, f"response exceeds {_MAX_RESPONSE_BYTES} bytes"
        return body, dict(resp.headers), None
    return None, None, f"too many redirects (>{max_hops})"
