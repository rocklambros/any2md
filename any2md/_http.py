"""SSRF-safe HTTP fetching for any2md.

Defenses against:
  - non-http(s) schemes
  - URLs resolving to non-public addresses (private, multicast, CGNAT, etc.)
  - DNS rebinding via redirect (per-hop revalidation)
  - DNS rebinding INTRA-hop (IP pinned through to socket.create_connection,
    so the IP we validated is the IP we connect to)
  - Environment-proxy bypass (ProxyHandler({}) suppresses HTTP_PROXY/HTTPS_PROXY)
  - Decompression / huge-response DoS (20 MB body cap)
  - Redirect loops / excessive hops (max 3)
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request

from any2md import __version__

_MAX_REDIRECT_HOPS = 3
_FETCH_TIMEOUT = 15  # seconds
_MAX_RESPONSE_BYTES = 20 * 1024 * 1024  # 20 MB cap on body read
_USER_AGENT = f"any2md/{__version__}"


def _addr_allowed(addr) -> bool:
    """Allowlist policy: globally routable, non-multicast, non-unspecified."""
    return bool(addr.is_global) and not addr.is_multicast and not addr.is_unspecified


def _resolve_and_validate(hostname: str) -> tuple[list[str], str | None]:
    """One-shot DNS resolution + IP-class validation.

    Returns ``(ips, None)`` on success or ``([], error)`` on rejection.
    Deny-on-any: if ANY resolved address fails policy, the whole hostname
    is rejected (defends against multi-record split-result attacks).
    """
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return [], f"cannot resolve host: {hostname}"
    ips: list[str] = []
    for *_, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if not _addr_allowed(addr):
            return [], f"URL resolves to disallowed address: {addr}"
        ips.append(ip_str)
    if not ips:
        return [], f"no usable address for {hostname}"
    return ips, None


def validate_url(url: str) -> str | None:
    """Validate scheme + hostname + IP class. Returns error or None.

    One-shot DNS resolution; intra-hop rebind defense lives in
    :func:`safe_fetch` (which pins the connection to the resolved IP).
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        return f"unsupported scheme: {parsed.scheme!r}"
    if not parsed.hostname:
        return f"no hostname in URL: {url}"
    _ips, err = _resolve_and_validate(parsed.hostname)
    return err


class _NoFollowRedirect(urllib.request.HTTPRedirectHandler):
    """Disable urllib's automatic redirect following."""

    def redirect_request(self, *args, **kwargs):  # noqa: ARG002
        return None


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, *args, pinned_ip: str, **kwargs):
        super().__init__(host, *args, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self):
        sock = socket.create_connection(
            (self._pinned_ip, self.port), timeout=self.timeout
        )
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
        # SNI + cert validation use the original hostname, NOT the IP
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, *args, pinned_ip: str, **kwargs):
        super().__init__(host, *args, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self):
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port), timeout=self.timeout
        )


def _build_pinned_opener(pinned_ip: str, scheme: str) -> urllib.request.OpenerDirector:
    """Build an opener that:
       - suppresses HTTP_PROXY/HTTPS_PROXY env (ProxyHandler({}))
       - disables urllib's auto-redirect (we walk hops manually)
       - pins HTTP/S connections to the validated IP
    """
    proxy_handler = urllib.request.ProxyHandler({})
    no_redirect = _NoFollowRedirect()

    if scheme == "https":
        class _Handler(urllib.request.HTTPSHandler):
            def https_open(self, req):  # noqa: D401
                return self.do_open(
                    lambda host, **kw: _PinnedHTTPSConnection(
                        host, pinned_ip=pinned_ip, **kw
                    ),
                    req,
                )
        pinned_handler = _Handler()
    else:
        class _Handler(urllib.request.HTTPHandler):
            def http_open(self, req):  # noqa: D401
                return self.do_open(
                    lambda host, **kw: _PinnedHTTPConnection(
                        host, pinned_ip=pinned_ip, **kw
                    ),
                    req,
                )
        pinned_handler = _Handler()

    return urllib.request.build_opener(proxy_handler, no_redirect, pinned_handler)


def safe_fetch(
    url: str,
    *,
    method: str = "GET",
    max_hops: int = _MAX_REDIRECT_HOPS,
) -> tuple[bytes | None, dict | None, str | None]:
    """Fetch ``url`` with manual redirect walking + per-hop revalidation
    + IP-pinned connection.

    Returns ``(body, headers, None)`` on 2xx, or ``(None, None, error)``
    on rejection / failure.
    """
    visited: list[str] = []
    current = url
    for hop in range(max_hops + 1):
        if current in visited:
            return None, None, "redirect loop"
        visited.append(current)

        parsed = urllib.parse.urlsplit(current)
        if parsed.scheme not in ("http", "https"):
            return None, None, f"unsupported scheme: {parsed.scheme!r}"
        if not parsed.hostname:
            return None, None, f"no hostname in URL: {current}"

        ips, err = _resolve_and_validate(parsed.hostname)
        if err:
            return None, None, err

        opener = _build_pinned_opener(ips[0], parsed.scheme)
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
