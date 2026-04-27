"""Post-processing pipeline runner.

See spec §4. Two lanes (structured / text) merge into shared cleanup
which always runs last. Each stage is a pure str -> str function that
must be a no-op on input it does not match.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

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
    # Explicit backend selection. ``None`` preserves the existing
    # auto-select behavior (Docling when installed, else format-specific
    # fallback). When set, the converter MUST honor the choice or fail
    # the file with a clear error if the backend is incompatible with
    # the input format (e.g. ``"mammoth"`` on a PDF, ``"pymupdf4llm"``
    # on a DOCX).
    backend: Literal["docling", "pymupdf4llm", "mammoth"] | None = None
    # --auto-id wiring. When ``auto_id`` is True, ``frontmatter.compose``
    # emits a generated ``document_id``. The prefix and type_code are
    # used as-is; Phase 4 hardcodes "LOCAL"/"DOC" and Task 5 wires
    # config-driven overrides via .any2md.toml [document_id].
    auto_id: bool = False
    auto_id_prefix: str = "LOCAL"
    auto_id_type_code: str = "DOC"
    # ``frontmatter_overrides`` is the parsed merge of ``.any2md.toml``,
    # ``--meta-file``, and CLI ``--meta KEY=VAL`` arguments (highest
    # priority last). Forwarded into ``frontmatter.compose`` so user-
    # supplied values replace derived fields. ``None`` means "no
    # overrides" (the common case).
    frontmatter_overrides: dict[str, Any] | None = field(default=None)
    # v1.0.2: when True (default), the heuristics author-extraction chain
    # is allowed to call the public arxiv API to enrich frontmatter for
    # PDFs whose filename matches the arxiv ID pattern. Set to False via
    # ``--no-arxiv-lookup`` to disable the network call (airgapped envs
    # or when offline behavior is required).
    arxiv_lookup: bool = True
    # v1.0.5: DOCX-only. When True (default) and Docling emits any
    # WARNING from ``docling.backend.msword_backend`` during conversion,
    # any2md re-runs the file through the mammoth+markdownify lane and
    # uses that output. Docling silently drops list items in a known
    # malformed-input path (msword_backend.py:1377/1675), so a Docling
    # warning means the Markdown is missing content. Disable via
    # ``--no-docx-fallback-on-warn`` to keep Docling output even when
    # warnings fire (e.g. when comparing backends explicitly).
    docx_fallback_on_warn: bool = True


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
