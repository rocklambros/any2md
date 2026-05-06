"""Test that _USER_AGENT in _http.py reflects the package version."""

from __future__ import annotations

import any2md
from any2md._http import _USER_AGENT


def test_user_agent_matches_version():
    assert _USER_AGENT == f"any2md/{any2md.__version__}"
