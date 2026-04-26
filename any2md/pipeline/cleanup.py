"""Shared cleanup stages (always last). See spec §4.3."""

from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from any2md.pipeline import PipelineOptions

Stage = Callable[[str, "PipelineOptions"], str]

# Filled in by Tasks 9–15.
STAGES: list[Stage] = []
