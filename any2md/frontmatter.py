"""SSRM-compatible YAML frontmatter emitter.

See spec §3 (frontmatter contract) and §5.0 (SourceMeta dataclass).
This module is the single producer of the YAML block — converters
never touch YAML directly.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date as _date_cls
from typing import Any, Literal

from any2md.pipeline import Lane, PipelineOptions


def compute_content_hash(body: str) -> str:
    """SHA-256 of NFC-normalized, LF-line-ended body. SSRM §5.1.

    The body MUST be the post-pipeline output (after C1-C5). This function
    re-applies NFC and LF normalization defensively so callers can pass any
    string and get a stable hash.
    """
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def generate_document_id(
    body: str, prefix: str = "LOCAL", type_code: str = "DOC"
) -> str:
    """Generate an SSRM-conformant ``document_id`` from body content.

    Pattern: ``{PREFIX}-{YYYY}-{TYPE}-{SHA8}``.

    Used by ``--auto-id``. The ``SHA8`` is the first 8 hex chars of the
    NFC + LF body's SHA-256 (i.e. ``compute_content_hash(body)[:8]``),
    so two bodies that share a ``content_hash`` share an ``id``.
    """
    full_hash = compute_content_hash(body)
    return f"{prefix}-{_date_cls.today().year}-{type_code}-{full_hash[:8]}"


@dataclass
class SourceMeta:
    title_hint: str | None
    authors: list[str]
    organization: str | None
    date: str | None              # ISO-8601 YYYY-MM-DD
    keywords: list[str]
    pages: int | None             # PDFs only
    word_count: int | None        # DOCX/HTML/TXT (post-cleanup)
    source_file: str | None
    source_url: str | None
    doc_type: Literal["pdf", "docx", "html", "txt"]   # v0.7-compat extension
    extracted_via: Literal[
        "docling", "pymupdf4llm", "mammoth+markdownify",
        "trafilatura", "trafilatura+bs4_fallback", "heuristic",
    ]
    lane: Lane


def estimate_tokens(body: str) -> int:
    """Rough token estimate: ceil(chars / 4). Spec §3.2."""
    return math.ceil(len(body) / 4)


_H2_RE = re.compile(r"^##\s+\S.*$", re.MULTILINE)


def recommend_chunk_level(body: str) -> str:
    """Spec §3.2: h3 if any H2 section body > 1500 estimated tokens; else h2."""
    matches = list(_H2_RE.finditer(body))
    if not matches:
        return "h2"
    boundaries = [m.start() for m in matches] + [len(body)]
    for start, end in zip(boundaries, boundaries[1:]):
        section = body[start:end]
        if estimate_tokens(section) > 1500:
            return "h3"
    return "h2"


_H1_LINE_RE = re.compile(r"^#\s+\S.*$", re.MULTILINE)
_HEADING_LINE_RE = re.compile(r"^#{1,6}\s+\S")


def extract_abstract(body: str) -> str | None:
    """First non-heading paragraph >= 80 chars after H1, capped at 400.

    Returns None if no qualifying paragraph exists. Spec §3.2.
    """
    h1 = _H1_LINE_RE.search(body)
    if not h1:
        return None

    # Walk paragraphs after the H1 (split on blank lines).
    after = body[h1.end():]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", after)]
    for para in paragraphs:
        if not para:
            continue
        if _HEADING_LINE_RE.match(para):
            continue
        if len(para) < 80:
            continue
        # Truncate at last sentence boundary <= 400.
        if len(para) <= 400:
            return para
        head = para[:400]
        last_dot = head.rfind(".")
        if last_dot >= 80:
            return head[: last_dot + 1]
        return head.rstrip() + "..."
    return None


_FIRST_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_MD_EMPHASIS_RE = re.compile(r"[*_]+")


def derive_title(body: str, title_hint: str | None, fallback: str) -> str:
    """Pick title: first H1, else hint, else cleaned filename stem."""
    m = _FIRST_H1_RE.search(body)
    if m:
        title = _MD_EMPHASIS_RE.sub("", m.group(1)).strip()
        if title:
            return title
    if title_hint:
        return title_hint.strip()
    stem = fallback.rsplit(".", 1)[0]
    return stem.replace("_", " ").strip() or "Untitled"


def _yaml_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
             .replace('"', '\\"')
             .replace("\n", "\\n")
             .replace("\r", "\\r")
    )


def _emit_value(value: Any) -> str:
    """Emit a scalar or simple list as YAML (one line)."""
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{_yaml_escape(value)}"'
    if isinstance(value, (int, float)):
        return str(value)
    raise TypeError(f"unsupported scalar: {type(value)}")


def _emit_array(values: list[str]) -> str:
    if not values:
        return "[]"
    items = ", ".join(_emit_value(v) for v in values)
    return f"[{items}]"


def compose(body: str, meta: SourceMeta, options: PipelineOptions) -> str:
    """Build a complete SSRM-compatible Markdown document.

    Steps:
    1. Normalize body to NFC + LF endings (matches content_hash invariant).
    2. Derive title, content_hash, token_estimate, chunk_level, abstract.
    3. Emit YAML frontmatter in spec §3.2-3.4 order.
    4. Concatenate frontmatter + body.
    """
    # 1. Normalize body
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    body = unicodedata.normalize("NFC", body)
    if not body.endswith("\n"):
        body += "\n"

    # 2. Derive
    fallback = meta.source_file or meta.source_url or "untitled"
    title = derive_title(body, meta.title_hint, fallback)
    content_hash = compute_content_hash(body)
    token_est = estimate_tokens(body)
    chunk_level = recommend_chunk_level(body)
    abstract = extract_abstract(body) if token_est >= 500 else None
    today = _date_cls.today().isoformat()
    fm_date = meta.date or today

    # 3. Emit YAML in SSRM-defined order
    lines: list[str] = ["---"]
    lines.append(f"title: {_emit_value(title)}")
    if options.auto_id:
        doc_id = generate_document_id(
            body,
            prefix=options.auto_id_prefix,
            type_code=options.auto_id_type_code,
        )
        lines.append(f'document_id: "{doc_id}"')
    else:
        lines.append('document_id: ""')
    lines.append('version: "1"')
    lines.append(f"date: {_emit_value(fm_date)}")
    lines.append('status: "draft"')
    lines.append('document_type: ""')
    lines.append("content_domain: []")
    lines.append(f"authors: {_emit_array(meta.authors)}")
    lines.append(f"organization: {_emit_value(meta.organization or '')}")
    lines.append("generation_metadata:")
    lines.append('  authored_by: "unknown"')
    lines.append(f'content_hash: "{content_hash}"')
    if meta.keywords:
        lines.append(f"keywords: {_emit_array(meta.keywords)}")
    lines.append(f"token_estimate: {token_est}")
    lines.append(f'recommended_chunk_level: "{chunk_level}"')
    if abstract:
        lines.append(f"abstract_for_rag: {_emit_value(abstract)}")
    # any2md extension fields (preserved from v0.7 for traceability)
    if meta.source_file:
        lines.append(f"source_file: {_emit_value(meta.source_file)}")
    if meta.source_url:
        lines.append(f"source_url: {_emit_value(meta.source_url)}")
    lines.append(f'type: "{meta.doc_type}"')          # v0.7-compat field (spec §3.2)
    lines.append(f'extracted_via: "{meta.extracted_via}"')  # v1.0 provenance extension
    if meta.pages is not None:
        lines.append(f"pages: {meta.pages}")
    if meta.word_count is not None:
        lines.append(f"word_count: {meta.word_count}")
    lines.append("---")
    lines.append("")  # blank line separator

    return "\n".join(lines) + "\n" + body
