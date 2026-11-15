"""SAGE-compatible YAML frontmatter emitter.

See spec §3 (frontmatter contract) and §5.0 (SourceMeta dataclass).
This module is the single producer of the YAML block — converters
never touch YAML directly.
"""

from __future__ import annotations

import hashlib
import math
import re
import sys
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date as _date_cls
from datetime import time as _time_cls
from typing import Any, Literal

from any2md import _logging, heuristics
from any2md.config import validate_document_id_settings
from any2md.utils import clean_iso_date
from any2md.pipeline import Lane, PipelineOptions


_RESERVED_OVERRIDE_KEYS = frozenset(
    {
        "content_hash",
        "token_estimate",
        "recommended_chunk_level",
        "extracted_via",
        "source_file",
        "lane",
    }
)

_VALID_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def _validate_keys(d: Mapping, *, path: str = "") -> None:
    """Recursively validate that every key matches ``_VALID_KEY_RE``.

    Raises ``ValueError`` on the first invalid key. ``path`` is the
    dotted prefix used to identify nested keys in the error message.
    """
    for k, v in d.items():
        full = f"{path}{k!r}"
        if not isinstance(k, str) or not _VALID_KEY_RE.match(k):
            raise ValueError(f"invalid frontmatter key: {full}")
        if isinstance(v, Mapping):
            _validate_keys(v, path=f"{path}{k}.")


def filter_reserved_overrides(
    overrides: Mapping[str, Any] | None,
    *,
    source_label: str = "overrides",
) -> dict[str, Any] | None:
    """Drop top-level reserved keys; emit stderr WARN per drop.

    Reserved keys are derived from the source document and must not be
    overridable via ``--meta``, ``--meta-file``, or ``.any2md.toml``.
    Nested dicts under non-reserved keys are returned untouched.
    """
    if overrides is None:
        return None
    out: dict[str, Any] = {}
    for k, v in overrides.items():
        if k in _RESERVED_OVERRIDE_KEYS:
            print(
                f"  WARN: ignoring {source_label} key {k!r} "
                f"— reserved (derived from source).",
                file=sys.stderr,
            )
            continue
        out[k] = v
    return out


def compute_content_hash(body: str) -> str:
    """SHA-256 of NFC-normalized, LF-line-ended body. SAGE §5.1.

    The body MUST be the post-pipeline output (after C1-C5). This function
    re-applies NFC and LF normalization defensively so callers can pass any
    string and get a stable hash.
    """
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def generate_document_id(
    body: str,
    prefix: str = "LOCAL",
    type_code: str = "DOC",
    *,
    year: int,
    content_hash: str | None = None,
) -> str:
    """Generate a SAGE-conformant ``document_id`` from body content.

    Pattern: ``{PREFIX}-{YYYY}-{TYPE}-{SEQ}``, which matches SAGE v1.0-RC1
    ``^[A-Z0-9]+-\\d{4}-[A-Z]{2,4}-\\d{3,}$``. Example:
    ``CSA-2025-GD-0422528348``.

    Used by ``--auto-id``. ``SEQ`` is the first 8 hex chars of the NFC + LF
    body's SHA-256 (``compute_content_hash(body)[:8]``) read as a 32-bit
    integer and zero-padded to 10 decimal digits, so two bodies that share
    a ``content_hash`` and a ``date`` year share an ``id``.

    Args:
        body: Post-pipeline body.
        prefix: ``auto_id_prefix``. Must match ``^[A-Z0-9]+$``.
        type_code: ``auto_id_type_code``. Must match ``^[A-Z]{2,4}$``.
        year: Year of the document's emitted ``date``. Keyword-only, so a
            1.2.x positional call ``(body, prefix, type_code)`` fails with
            ``TypeError`` instead of binding a prefix to the year.
        content_hash: ``compute_content_hash(body)`` when the caller already
            has it. ``compose()`` passes its own value, so the id and the
            emitted ``content_hash`` cannot disagree.

    Raises:
        ValueError: if ``prefix``, ``type_code``, or ``year`` would make a
            non-conforming id. The CLI validates config values before any
            file is read. This guard covers library callers that build
            ``PipelineOptions`` directly.
    """
    validate_document_id_settings(prefix, type_code)
    if isinstance(year, bool) or not isinstance(year, int) or not 0 <= year <= 9999:
        raise ValueError(f"document_id year must be 0-9999, got {year!r}")
    if content_hash is None:
        content_hash = compute_content_hash(body)
    elif not _CONTENT_HASH_RE.fullmatch(content_hash):
        raise ValueError(
            f"content_hash must be 64 lowercase hex characters, got {content_hash!r}"
        )
    full_hash = content_hash
    seq = int(full_hash[:8], 16)
    # 2**32 - 1 has 10 digits, so a fixed width keeps every id the same length.
    return f"{prefix}-{year:04d}-{type_code}-{seq:010d}"


_CONTENT_HASH_RE = re.compile(r"[0-9a-f]{64}")


def has_explicit_document_id(overrides: Mapping[str, Any] | None) -> bool:
    """True when an override layer sets a non-blank ``document_id``.

    An explicit id wins over ``--auto-id``. A blank value counts as unset,
    so a template that keeps ``document_id = ""`` as a placeholder does not
    silently turn ``--auto-id`` off. Blank means ``None``, a whitespace-only
    string, or an empty list or table (``--meta document_id=,`` parses to
    ``[]``).
    """
    if not overrides or "document_id" not in overrides:
        return False
    value = overrides["document_id"]
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


# The time an override may carry after its date. A fixed ASCII pattern, not
# ``datetime.fromisoformat``, whose accepted forms change between Python
# releases (3.15 accepts ``T24:00``, 3.12 accepts ``T10,5``).
_ISO_TIME_RE = re.compile(
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]"
    r"(?::[0-5][0-9](?:\.[0-9]{1,9})?)?"
    r"(?:Z|[+-](?:[01][0-9]|2[0-3])(?::?[0-5][0-9])?)?"
)
# The accepted forms, named in errors and docs so "ISO time" is not a guess.
AUTO_ID_TIME_FORMS = (
    "HH:MM, optional :SS and a fraction of 1 to 9 digits, and an optional "
    "Z or a +/- offset as HH:MM, HHMM, or HH"
)


def normalize_auto_id_date(value: Any) -> str:
    """Return the ``YYYY-MM-DD`` that ``--auto-id`` emits for a ``date`` value.

    One rule for every source, matching what the document readers keep: a
    ``date``/``datetime`` (TOML date or datetime from a meta file) reduced to
    its calendar date, or a string that is an ASCII ``YYYY-MM-DD`` calendar
    date, optionally followed by ``T`` or a space and a time in one of the
    ``AUTO_ID_TIME_FORMS`` (``HH:MM``, optional ``:SS`` and a fraction of up
    to 9 digits, optional ``Z`` or a ``+HH:MM``, ``+HHMM``, or ``+HH``
    offset), after surrounding whitespace is stripped. ``compose()`` emits the result, so ``date`` is always a full
    calendar date when ``--auto-id`` generates an id.

    Raises:
        ValueError: for anything else, including a bare year, ``2025-3``,
            ``2025-13-99``, or a malformed time. Falling back to the clock
            would make the id depend on when the conversion ran.
    """
    if isinstance(value, _date_cls):
        # ``datetime`` subclasses ``date``, so this covers both.
        return value.isoformat()[:10]
    if isinstance(value, str):
        text = value.strip()
        head = clean_iso_date(text[:10])
        if head is not None:
            if len(text) == 10:
                return head
            if text[10] in "T " and _ISO_TIME_RE.fullmatch(text[11:]):
                return head
    raise ValueError(
        "--auto-id needs date as an ASCII calendar date YYYY-MM-DD, "
        f"optionally followed by T or a space and a time ({AUTO_ID_TIME_FORMS}), "
        f"got date {value!r}"
    )


def year_of_date(value: Any) -> int:
    """Return the year of a ``date`` value under the ``--auto-id`` rule.

    Raises:
        ValueError: see ``normalize_auto_id_date``.
    """
    return int(normalize_auto_id_date(value)[:4])


@dataclass
class SourceMeta:
    title_hint: str | None
    authors: list[str]
    organization: str | None
    date: str | None  # ISO-8601 YYYY-MM-DD
    keywords: list[str]
    pages: int | None  # PDFs only
    word_count: int | None  # DOCX/PPTX/XLSX/HTML/TXT (post-cleanup)
    source_file: str | None
    source_url: str | None
    doc_type: Literal[
        "pdf", "docx", "pptx", "xlsx", "html", "txt"
    ]  # v0.7-compat extension
    extracted_via: Literal[
        "docling",
        "pymupdf4llm",
        "mammoth+markdownify",
        "trafilatura",
        "trafilatura+bs4_fallback",
        "heuristic",
    ]
    lane: Lane
    # v1.0.2: software/tool that produced the source (PDF Creator field for
    # PDFs, Application field for DOCX). Distinct from `organization`, which
    # is the human/legal entity. Default None to keep existing call sites
    # working without churn.
    produced_by: str | None = None
    # v1.2.0: HTML metadata title (og:title / <title> via trafilatura).
    # Emitted only when it differs from the final `title`, which follows
    # the body H1 (the page's visible heading).
    seo_title: str | None = None


def _same_title(a: str, b: str) -> bool:
    """Case- and whitespace-insensitive title equality."""
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


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
    after = body[h1.end() :]
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


_MD_EMPHASIS_RE = re.compile(r"[*_]+")


def derive_title(body: str, title_hint: str | None, fallback: str) -> str:
    """Pick title: first H1, else hint, else cleaned filename stem."""
    # Line scan, not ``^#\\s+(.+?)\\s*$``: that regex backtracked in
    # quadratic time on an H1 holding a long whitespace run (CWE-1333).
    for line in body.split("\n"):
        if line[:1] == "#" and line[1:2] in (" ", "\t") and line[1:].strip():
            title = _MD_EMPHASIS_RE.sub("", line[1:]).strip()
            if title:
                return title
            break
    if title_hint:
        return title_hint.strip()
    stem = fallback.rsplit(".", 1)[0]
    return stem.replace("_", " ").strip() or "Untitled"


# Characters a YAML double-quoted scalar cannot carry raw. Strings reach the
# emitter from untrusted document metadata and discovered config files, so
# each of these is escaped: a raw C0 or C1 control or noncharacter makes the
# frontmatter invalid YAML, and a raw NEL, LS, or PS is folded to a space on
# read-back. Tab is printable in YAML and stays as is.
_YAML_UNSAFE_RE = re.compile(
    r"[\x00-\x08\x0a-\x1f\x7f-\x9f\u2028\u2029\ufeff\ud800-\udfff\ufffe\uffff]"
)


def _yaml_escape_char(match: re.Match[str]) -> str:
    ch = match.group(0)
    if ch == "\n":
        return "\\n"
    if ch == "\r":
        return "\\r"
    code = ord(ch)
    return f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}"


def _yaml_escape(value: str) -> str:
    """Escape ``value`` for a YAML double-quoted scalar that round-trips."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return _YAML_UNSAFE_RE.sub(_yaml_escape_char, escaped)


class FrontmatterEmitError(ValueError):
    """A field value has no YAML emission rule.

    Subclasses ``ValueError`` because every converter already reports
    ``ValueError`` as a per-file failure. A ``TypeError`` would escape the
    txt, docx, and pdf error boundaries and end the whole batch.
    """


def _emit_value(value: Any) -> str:
    """Emit a scalar as YAML (one line)."""
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{_yaml_escape(value)}"'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (_date_cls, _time_cls)):
        # TOML dates, times, and datetimes from --meta-file or .any2md.toml.
        # Emit them quoted, the same way the built-in ``date`` field is
        # emitted. Unquoted, a YAML 1.1 loader such as PyYAML returns date
        # and datetime objects but leaves a time as a string, and YAML 1.2
        # core-schema loaders return strings for all three. Quoting gives
        # every consumer the same string type for every value.
        # ``datetime`` subclasses ``date``, so this branch covers all three.
        return f'"{value.isoformat()}"'
    raise FrontmatterEmitError(f"unsupported frontmatter value: {type(value).__name__}")


def _list_item_text(value: Any) -> str:
    """Convert one list item to the string the flow-list emitter quotes."""
    if isinstance(value, (dict, list)):
        # Lists emit in flow style as quoted strings. A TOML array of tables
        # or a nested array would come out as Python repr text, so fail the
        # file instead. A block-style emitter for mappings inside lists is
        # out of proportion for SAGE fields, which are flat scalar lists.
        raise FrontmatterEmitError(
            f"unsupported frontmatter list item: {type(value).__name__}"
        )
    if isinstance(value, (_date_cls, _time_cls)):
        # ``str(datetime)`` uses a space separator. Use the same ISO form
        # the scalar path emits.
        return value.isoformat()
    return str(value)


def _emit_array(values: list[str]) -> str:
    if not values:
        return "[]"
    items = ", ".join(_emit_value(v) for v in values)
    return f"[{items}]"


def _normalize_body(body: str) -> str:
    """Normalize body to NFC + LF endings, ensuring trailing newline."""
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    body = unicodedata.normalize("NFC", body)
    if not body.endswith("\n"):
        body += "\n"
    return body


def _build_fields(
    body: str, meta: SourceMeta, options: PipelineOptions
) -> dict[str, Any]:
    """Build the ordered field map for the SAGE frontmatter block.

    Returns an insertion-ordered dict matching spec §3.2-3.4. Only fields
    that should be emitted are present; conditional fields (e.g. ``pages``,
    ``keywords``, ``abstract_for_rag``) are omitted when empty so callers
    can tell "absent" apart from "blank".
    """
    fallback = meta.source_file or meta.source_url or "untitled"
    title_raw = derive_title(body, meta.title_hint, fallback)
    arxiv_id = heuristics.is_arxiv_filename(meta.source_file or "")
    title = heuristics.refine_title(
        title_raw,
        body,
        source_url=meta.source_url,
        profile=options.profile,
    )
    content_hash = compute_content_hash(body)
    token_est = estimate_tokens(body)
    chunk_level = recommend_chunk_level(body)
    abstract_raw = extract_abstract(body) if token_est >= 500 else None
    abstract = (
        heuristics.refine_abstract(abstract_raw, body, profile=options.profile)
        if token_est >= 500
        else None
    )
    # Author chain — only invoke heuristics when meta.authors is empty.
    # Caller-supplied authors (e.g. from extractor metadata) take priority.
    authors = list(meta.authors)
    if not authors:
        authors = heuristics.extract_authors(
            body,
            title_hint=meta.title_hint,
            arxiv_id=arxiv_id,
            arxiv_lookup_enabled=options.arxiv_lookup,
            profile=options.profile,
        )
    today = _date_cls.today().isoformat()
    fm_date = meta.date or today

    fields: dict[str, Any] = {}
    fields["title"] = title
    # Placeholder that keeps the field's position. compose() fills it for
    # --auto-id after overrides merge, because YEAR comes from the final date.
    fields["document_id"] = ""
    fields["version"] = "1"
    fields["date"] = fm_date
    fields["status"] = "draft"
    fields["document_type"] = ""
    fields["content_domain"] = []
    fields["authors"] = authors
    fields["organization"] = meta.organization or ""
    fields["generation_metadata"] = {"authored_by": "unknown"}
    fields["content_hash"] = content_hash
    if meta.keywords:
        fields["keywords"] = list(meta.keywords)
    fields["token_estimate"] = token_est
    fields["recommended_chunk_level"] = chunk_level
    if abstract:
        fields["abstract_for_rag"] = abstract
    # any2md extension fields (preserved from v0.7 for traceability)
    if meta.source_file:
        fields["source_file"] = meta.source_file
    if meta.source_url:
        fields["source_url"] = meta.source_url
    fields["type"] = meta.doc_type  # v0.7-compat field (spec §3.2)
    fields["extracted_via"] = meta.extracted_via  # v1.0 provenance extension
    if meta.produced_by is not None:
        fields["produced_by"] = meta.produced_by  # v1.0.2 extension (spec §6.1)
    seo_title = (meta.seo_title or "").strip()
    if seo_title and not _same_title(seo_title, title):
        fields["seo_title"] = seo_title  # v1.2.0 extension (HTML only)
    if meta.pages is not None:
        fields["pages"] = meta.pages
    if meta.word_count is not None:
        fields["word_count"] = meta.word_count
    return fields


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge ``overrides`` into ``base`` and return a new dict.

    Nested dicts merge recursively; lists and scalars from ``overrides``
    replace those in ``base`` (no list extension). Override-only keys are
    appended to the end of the field map in their iteration order.
    """
    out = dict(base)
    for key, val in overrides.items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def _emit_field(key: str, value: Any, lines: list[str], depth: int = 0) -> None:
    """Emit one ``key: value`` line (or block) into ``lines``.

    Nested dicts recurse with two more spaces of indent per level, so a
    list under ``--meta a.b=x,y`` renders the same way a top-level list does.
    """
    indent = "  " * depth
    if isinstance(value, dict):
        if not value:
            # A bare ``key:`` reads back as null, so an empty TOML table
            # needs the explicit flow form to stay a mapping.
            lines.append(f"{indent}{key}: {{}}")
            return
        lines.append(f"{indent}{key}:")
        for subkey, subval in value.items():
            _emit_field(subkey, subval, lines, depth + 1)
        return
    if isinstance(value, list):
        # Items emit as quoted strings (matches SAGE §3 fields).
        items = [_list_item_text(v) for v in value]
        lines.append(f"{indent}{key}: {_emit_array(items)}")
        return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        lines.append(f"{indent}{key}: {value}")
        return
    # Default: scalar/string emission.
    lines.append(f"{indent}{key}: {_emit_value(value)}")


def _emit_yaml_with_body(fields: dict[str, Any], body: str) -> str:
    """Serialize ``fields`` as YAML frontmatter and concatenate ``body``."""
    lines: list[str] = ["---"]
    for key, value in fields.items():
        _emit_field(key, value, lines)
    lines.append("---")
    lines.append("")  # blank line separator
    return "\n".join(lines) + "\n" + body


def compose(
    body: str,
    meta: SourceMeta,
    options: PipelineOptions,
    overrides: dict[str, Any] | None = None,
) -> str:
    """Build a complete SAGE-compatible Markdown document.

    Steps:
    1. Normalize body to NFC + LF endings (matches content_hash invariant).
    2. Derive title, content_hash, token_estimate, chunk_level, abstract.
    3. Deep-merge ``overrides`` (from ``--meta`` / ``--meta-file`` /
       ``.any2md.toml``) over the derived field map.
    4. With ``--auto-id``, generate ``document_id`` from the body and the
       year of the merged ``date``, unless an override set a non-empty
       ``document_id``.
    5. Emit YAML frontmatter in spec §3.2-3.4 order and concatenate the body.

    Raises:
        ValueError: on an invalid override key, or when ``--auto-id`` cannot
            read a year from the merged ``date``.
    """
    body = _normalize_body(body)
    overrides = filter_reserved_overrides(overrides, source_label="compose()")
    if overrides:
        _validate_keys(overrides)
    fields = _build_fields(body, meta, options)
    if overrides:
        fields = _deep_merge(fields, overrides)
    # An explicit non-empty document_id from any override layer wins,
    # unvalidated. content_hash is reserved, so fields still holds the
    # derived value.
    if options.auto_id and not has_explicit_document_id(overrides):
        # Emit the normalized date so the id's year and ``date`` agree and
        # ``date`` is always YYYY-MM-DD, whatever form the override took.
        fields["date"] = normalize_auto_id_date(fields["date"])
        fields["document_id"] = generate_document_id(
            body,
            prefix=options.auto_id_prefix,
            type_code=options.auto_id_type_code,
            year=int(fields["date"][:4]),
            content_hash=fields["content_hash"],
        )
    return _emit_yaml_with_body(fields, body)


_MAX_LOGGED_DATE_CHARS = 80


def warn_dropped_document_date(
    source_name: str, rejected: str | None, options: Any
) -> None:
    """Warn that a document's own date was dropped for the mtime fallback.

    Called by each converter after its metadata reader returns, because only
    the converter knows, from ``options``, whether a ``date`` override replaces the document's
    date. With a non-blank override the dropped value is unused, so nothing
    is printed. With a blank one the notice says ``date`` is left blank. The value is truncated, then ``repr()``-escaped, and
    ``_logging.warn`` keeps the whole message on one line, so hostile
    metadata cannot forge or flood terminal output. This is informational
    and is not counted toward ``--strict``.
    """
    if rejected is None:
        return
    overrides = options.frontmatter_overrides
    # A non-blank override replaces the document's date, so the dropped
    # value is unused and nothing is printed. A blank or null override is
    # still merged, so ``date`` ends up blank rather than the mtime, and the
    # notice says so. When --auto-id generates an id, compose() fails the
    # file on that blank date, and its FAIL line is the explanation.
    outcome = "using the file modification time"
    if overrides and "date" in overrides:
        override = overrides["date"]
        if override is not None and not (
            isinstance(override, str) and not override.strip()
        ):
            return
        if options.auto_id and not has_explicit_document_id(overrides):
            return
        outcome = "and the blank date override leaves date blank"
    # Truncate first and put the length note outside the quotes, so it
    # cannot be mistaken for part of the document's value.
    shown = repr(rejected[:_MAX_LOGGED_DATE_CHARS])
    if len(rejected) > _MAX_LOGGED_DATE_CHARS:
        shown += f"... ({len(rejected)} chars)"
    _logging.warn(
        f"{source_name}: ignoring document date {shown} (not a full "
        f"YYYY-MM-DD calendar date), {outcome}"
    )
