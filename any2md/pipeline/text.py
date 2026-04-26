"""Text-lane pipeline stages.

Phase 1: empty. Phase 3 fills T1–T6 (line-wrap repair, dehyphenate,
paragraph dedupe, TOC dedupe, header/footer strip, list/code restore).
"""

from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from any2md.pipeline import PipelineOptions

Stage = Callable[[str, "PipelineOptions"], str]

STAGES: list[Stage] = []
