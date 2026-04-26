"""Post-processing pipeline runner.

See spec §4. Two lanes (structured / text) merge into shared cleanup
which always runs last. Each stage is a pure str -> str function that
must be a no-op on input it does not match.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable, Literal

Lane = Literal["structured", "text"]
Profile = Literal["conservative", "aggressive", "maximum"]


@dataclass(frozen=True)
class PipelineOptions:
    profile: Profile = "aggressive"
    ocr_figures: bool = False
    save_images: bool = False
    strip_links: bool = False
    strict: bool = False
    high_fidelity: bool = False  # force Docling backend
    # --auto-id wiring. When ``auto_id`` is True, ``frontmatter.compose``
    # emits a generated ``document_id``. The prefix and type_code are
    # used as-is; Phase 4 hardcodes "LOCAL"/"DOC" and Task 5 wires
    # config-driven overrides via .any2md.toml [document_id].
    auto_id: bool = False
    auto_id_prefix: str = "LOCAL"
    auto_id_type_code: str = "DOC"


Stage = Callable[[str, PipelineOptions], str]

# Stages may emit warnings via this contextvar; run() collects them.
_WARNINGS: ContextVar[list[str] | None] = ContextVar("_pipeline_warnings", default=None)


def emit_warning(msg: str) -> None:
    """Stage helper to record a non-fatal warning."""
    bucket = _WARNINGS.get()
    if bucket is not None:
        bucket.append(msg)


def run(text: str, lane: Lane, options: PipelineOptions) -> tuple[str, list[str]]:
    """Run lane-specific stages then shared cleanup. Returns (text, warnings)."""
    if lane not in ("structured", "text"):
        raise ValueError(f"unknown lane: {lane!r}")

    from any2md.pipeline import cleanup, structured, text as text_mod

    lane_stages = structured.STAGES if lane == "structured" else text_mod.STAGES

    warnings: list[str] = []
    token = _WARNINGS.set(warnings)
    try:
        for stage in lane_stages:
            text = stage(text, options)
        for stage in cleanup.STAGES:
            text = stage(text, options)
    finally:
        _WARNINGS.reset(token)

    return text, warnings
