"""Test that .devcontainer/requirements.lock includes every base dep
declared in pyproject.toml [project] dependencies."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent

try:
    import tomllib
except ImportError:
    pytest.skip("tomllib not available", allow_module_level=True)


def test_lockfile_contains_every_base_dep():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    deps = pyproject["project"]["dependencies"]
    lockfile = (ROOT / ".devcontainer" / "requirements.lock").read_text().lower()

    for dep in deps:
        # Skip deps with environment markers (e.g., 'tomli; python_version < "3.11"')
        # — those are excluded from the lockfile when generated on a Python
        # version that doesn't satisfy the marker.
        if ";" in dep:
            continue
        # Extract package name from "name>=1.0,<2" form
        name = re.split(r"[<>=!~\s\[]", dep, maxsplit=1)[0].strip().lower()
        # Match plain "name==" OR "name[extras]==" in lockfile
        pattern = re.compile(r"\n" + re.escape(name) + r"(?:\[[^\]]*\])?==")
        assert pattern.search(lockfile), (
            f"dep {name!r} missing from .devcontainer/requirements.lock"
        )


def test_lockfile_has_hashes():
    text = (ROOT / ".devcontainer" / "requirements.lock").read_text()
    assert "--hash=sha256:" in text, "lockfile must be generated with --generate-hashes"
