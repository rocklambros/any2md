"""Plain text to Markdown converter (v1.0)."""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

from any2md import pipeline
from any2md.converters import add_warnings, is_quiet
from any2md.frontmatter import SourceMeta, compose
from any2md.pipeline import PipelineOptions
from any2md.utils import read_text_with_fallback, sanitize_filename

# Existing structurize() heuristic stays in this file from v0.7 — keep it.
_SEPARATOR_RE = re.compile(r"^([=\-*_~])\1{2,}\s*$")
_BULLET_RE = re.compile(r"^[•–·]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\(?\d{1,3}[.)]\)?\s+(.*)$")
_LETTERED_RE = re.compile(r"^\(?[a-z][.)]\)?\s+(.*)$")
_INDENT_RE = re.compile(r"^(?:    |\t)(.*)$")
_ALL_CAPS_RE = re.compile(r"^[A-Z][A-Z0-9 /&,:\-]{2,78}$")


def _is_title_case(line: str) -> bool:
    words = line.split()
    if len(words) < 2:
        return False
    skip = {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "is",
    }
    caps = sum(1 for w in words if w[0].isupper() or w.lower() in skip)
    return caps >= len(words) * 0.7


def structurize(text: str) -> str:
    """Convert plain text to Markdown by detecting implicit structure.

    Unchanged from v0.7. Output goes through the v1.0 cleanup pipeline.
    """
    text = text.replace("\t", "    ")
    lines = text.split("\n")
    output: list[str] = []
    i = 0
    title_emitted = False
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()
        prev_stripped = lines[i - 1].strip() if i > 0 else ""
        next_stripped = lines[i + 1].strip() if i < n - 1 else ""

        sep_match = _SEPARATOR_RE.match(stripped)
        if sep_match and stripped:
            char = sep_match.group(1)
            if prev_stripped and output and output[-1].strip():
                prev_text = output[-1].strip()
                if not prev_text.startswith("#"):
                    if char == "=":
                        output[-1] = "# " + prev_text
                    else:
                        output[-1] = "## " + prev_text
                    i += 1
                    continue
            output.append("---")
            i += 1
            continue

        if _INDENT_RE.match(line) and stripped:
            block_lines: list[str] = []
            while i < n and (_INDENT_RE.match(lines[i]) or not lines[i].strip()):
                if not lines[i].strip():
                    j = i + 1
                    while j < n and not lines[j].strip():
                        j += 1
                    if j < n and _INDENT_RE.match(lines[j]):
                        block_lines.append("")
                        i += 1
                        continue
                    else:
                        break
                indent_m = _INDENT_RE.match(lines[i])
                block_lines.append(indent_m.group(1) if indent_m else lines[i])
                i += 1
            output.append("```")
            output.extend(block_lines)
            output.append("```")
            continue

        bullet_m = _BULLET_RE.match(stripped)
        if bullet_m:
            output.append("- " + bullet_m.group(1))
            i += 1
            continue

        num_m = _NUMBERED_RE.match(stripped)
        let_m = _LETTERED_RE.match(stripped) if not num_m else None
        if num_m:
            output.append("1. " + num_m.group(1))
            i += 1
            continue
        if let_m:
            output.append("1. " + let_m.group(1))
            i += 1
            continue

        if _ALL_CAPS_RE.match(stripped) and len(stripped) <= 80:
            if not next_stripped or i == n - 1:
                if not title_emitted:
                    output.append("# " + stripped.title())
                    title_emitted = True
                else:
                    output.append("## " + stripped.title())
                i += 1
                continue

        if (
            3 <= len(stripped) <= 80
            and not prev_stripped
            and not next_stripped
            and _is_title_case(stripped)
            and not stripped.endswith((".", "!", "?", ",", ";", ":"))
            and i > 0
        ):
            output.append("### " + stripped)
            i += 1
            continue

        output.append(line)
        i += 1

    return "\n".join(output)


def _build_meta(txt_path: Path, body: str) -> SourceMeta:
    return SourceMeta(
        title_hint=None,
        authors=[],
        organization=None,
        date=(
            date.fromtimestamp(txt_path.stat().st_mtime).isoformat()
            if txt_path.exists()
            else None
        ),
        keywords=[],
        pages=None,
        word_count=len(body.split()),
        source_file=txt_path.name,
        source_url=None,
        doc_type="txt",
        extracted_via="heuristic",
        lane="text",
    )


def convert_txt(
    txt_path: Path,
    output_dir: Path,
    options: PipelineOptions | None = None,
    force: bool = False,
    strip_links_flag: bool = False,
) -> bool:
    """Convert a plain-text file to v1.0 SSRM-compatible Markdown."""
    if options is None:
        options = PipelineOptions(strip_links=strip_links_flag)

    out_name = sanitize_filename(txt_path.name)
    out_path = output_dir / out_name
    if out_path.exists() and not force:
        print(f"  SKIP (exists): {out_name}")
        return True

    try:
        raw_text = read_text_with_fallback(txt_path)
        if not raw_text.strip():
            print(f"  FAIL: {txt_path.name} -- empty file", file=sys.stderr)
            return False

        md_text = structurize(raw_text)
        md_text, warnings = pipeline.run(md_text, "text", options)
        add_warnings(warnings)
        meta = _build_meta(txt_path, md_text)
        full = compose(md_text, meta, options, overrides=options.frontmatter_overrides)

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(full, encoding="utf-8", newline="\n")
        word_count = meta.word_count or 0
        suffix = f", {len(warnings)} warning(s)" if warnings else ""
        if not is_quiet():
            print(f"  OK: {out_name} ({word_count} words{suffix})")
        return True

    except (OSError, ValueError) as e:
        print(f"  FAIL: {txt_path.name} -- {e}", file=sys.stderr)
        return False
