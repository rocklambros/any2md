"""IPv6 forms that embed an IPv4 address must follow the IPv4 policy.

Python's ``is_global`` does not unwrap NAT64, 6to4, or IPv4-compatible
addresses, and it unwraps IPv4-mapped addresses only on builds that
carry the CVE-2024-4032 fix. The guard has to decide from the embedded
IPv4 itself so the result does not change with the interpreter.
"""

from __future__ import annotations

import ipaddress
import socket

import pytest

from any2md._http import _addr_allowed, validate_url

_BLOCKED = [
    # IPv4-mapped ::ffff:0:0/96
    "::ffff:127.0.0.1",
    "::ffff:10.0.0.1",
    "::ffff:169.254.169.254",
    "::ffff:100.100.100.200",
    "::ffff:0.0.0.0",
    # SIIT IPv4-translated ::ffff:0:0:0/96
    "::ffff:0:a00:1",
    "::ffff:0:a9fe:a9fe",
    # NAT64 well-known prefix 64:ff9b::/96
    "64:ff9b::a00:1",
    "64:ff9b::7f00:1",
    "64:ff9b::a9fe:a9fe",
    "64:ff9b::6464:64c8",
    # NAT64 local-use prefix 64:ff9b:1::/48, never globally routable
    "64:ff9b:1::a00:1",
    "64:ff9b:1::808:808",
    # 6to4 2002::/16
    "2002:7f00:1::1",
    "2002:a00:1::",
    "2002:a9fe:a9fe::1",
    "2002:6464:64c8::1",
    # Teredo 2001::/32
    "2001:0:4136:e378:8000:63bf:f5ff:fffe",
    "2001:0:a00:1::",
    # IPv4-compatible ::/96, deprecated by RFC 4291
    "::7f00:1",
    "::a00:1",
    "::808:808",
]

_ALLOWED = [
    "::ffff:8.8.8.8",
    "64:ff9b::808:808",
    "2002:808:808::1",
    "2606:4700:4700::1111",
]


def _gai(ip: str):
    return [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", (ip, 0, 0, 0))]


@pytest.mark.parametrize("ip", _BLOCKED)
def test_embedded_internal_ipv4_is_blocked(ip, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: _gai(ip))
    err = validate_url("https://attacker.example/")
    assert err is not None and "disallowed" in err


@pytest.mark.parametrize("ip", _ALLOWED)
def test_embedded_public_ipv4_is_allowed(ip, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: _gai(ip))
    assert validate_url("https://example.com/") is None


@pytest.mark.parametrize("ip", _BLOCKED)
def test_block_does_not_depend_on_ipv6_is_global(ip, monkeypatch):
    """Simulate an interpreter whose IPv6 ``is_global`` calls every
    address global, as pre-CVE-2024-4032 builds do for IPv4-mapped
    forms. The guard must still reject the embedded internal target."""
    monkeypatch.setattr(ipaddress.IPv6Address, "is_global", property(lambda self: True))
    assert _addr_allowed(ipaddress.ip_address(ip)) is False


def test_cgnat_ipv4_blocked_even_if_is_global_says_true(monkeypatch):
    monkeypatch.setattr(ipaddress.IPv4Address, "is_global", property(lambda self: True))
    assert _addr_allowed(ipaddress.ip_address("100.100.100.200")) is False
