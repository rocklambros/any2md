"""Structured-lane pipeline stages.

Phase 1: empty. Phase 2 fills S1–S4 (figure caption lift, table compactor,
citation normalizer, heading hierarchy).
"""

from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from any2md.pipeline import PipelineOptions

Stage = Callable[[str, "PipelineOptions"], str]

STAGES: list[Stage] = []
