"""Optional sanity checks. Used by the CLI to surface warnings."""

from __future__ import annotations

import re

from any2md.frontmatter import compute_content_hash

_HEADING_RE = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)


def check_heading_hierarchy(body: str) -> list[str]:
    """Return a list of human-readable issues. Empty list = clean."""
    issues: list[str] = []
    levels = [len(m.group(1)) for m in _HEADING_RE.finditer(body)]
    if sum(1 for level in levels if level == 1) != 1:
        issues.append("H1 count is not exactly 1")
    for prev, curr in zip(levels, levels[1:]):
        if curr > prev + 1:
            issues.append(f"heading level skip h{prev} -> h{curr}")
            break
    return issues


def check_content_hash_round_trip(body: str, expected: str) -> bool:
    return compute_content_hash(body) == expected
