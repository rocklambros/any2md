"""Test that publish.yml has correct permissions and attestations."""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).parent.parent.parent
PUBLISH_YML = ROOT / ".github" / "workflows" / "publish.yml"


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(PUBLISH_YML.read_text())


def test_top_level_permissions_contents_read(workflow):
    assert workflow.get("permissions") == {"contents": "read"}


def test_publish_testpypi_has_id_token_write(workflow):
    job = workflow["jobs"]["publish-testpypi"]
    assert job["permissions"]["id-token"] == "write"


def test_publish_pypi_has_id_token_write(workflow):
    job = workflow["jobs"]["publish-pypi"]
    assert job["permissions"]["id-token"] == "write"


def test_both_publish_steps_have_attestations_true(workflow):
    for job_name in ("publish-testpypi", "publish-pypi"):
        job = workflow["jobs"][job_name]
        publish_step = next(
            s for s in job["steps"]
            if "pypa/gh-action-pypi-publish" in s.get("uses", "")
        )
        assert publish_step["with"]["attestations"] is True, (
            f"{job_name} must have attestations: true"
        )
