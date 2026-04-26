"""Tests for the validators module."""

import pytest

from any2md.validators import (
    check_content_hash_round_trip,
    check_heading_hierarchy,
)


def test_heading_hierarchy_clean_doc():
    issues = check_heading_hierarchy("# A\n\n## B\n\n### C\n")
    assert issues == []


def test_heading_hierarchy_missing_h1():
    issues = check_heading_hierarchy("## B\n\n### C\n")
    assert any("H1" in i for i in issues)


def test_heading_hierarchy_skip():
    issues = check_heading_hierarchy("# A\n\n#### D\n")
    assert any("skip" in i.lower() for i in issues)


def test_content_hash_round_trip_pass():
    body = "# Title\n\nbody.\n"
    from any2md.frontmatter import compute_content_hash
    expected = compute_content_hash(body)
    assert check_content_hash_round_trip(body, expected) is True


def test_content_hash_round_trip_fail():
    body = "# Title\n\nbody.\n"
    assert check_content_hash_round_trip(body, "deadbeef" * 8) is False
