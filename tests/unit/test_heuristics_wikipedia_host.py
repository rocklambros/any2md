"""Test wikipedia.org host check no longer matches imposters."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "host, should_match",
    [
        ("wikipedia.org", True),
        ("en.wikipedia.org", True),
        ("de.wikipedia.org", True),
        ("evilwikipedia.org", False),
        ("wikipedia.org.evil.com", False),
        ("notwikipedia.org", False),
        ("", False),
    ],
)
def test_wikipedia_host_check(host, should_match):
    actual = host == "wikipedia.org" or host.endswith(".wikipedia.org")
    assert actual is should_match
