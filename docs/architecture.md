# Architecture

This document is for contributors and for anyone trying to understand how
any2md produces its output. It covers the pipeline shape, the stage catalog,
the `SourceMeta` contract, and the procedure for adding new converters or
stages.

For a user-facing orientation, see the [README](../README.md). For the output
shape this pipeline produces, see [output-format.md](output-format.md). For
the CLI surface that drives this code, see
[cli-reference.md](cli-reference.md).

## High-level data flow

```
                  any2md  v1.0.2
                       │
                  ┌────┴────┐
              CLI │ cli.py  │  parse args, classify URL/file/dir,
                  └────┬────┘  pick converter, route flags
                       │
            ┌──────────┼──────────┐
            ▼          ▼          ▼
   converters/    converters/    converters/
     pdf.py        docx.py     html.py  txt.py
        │            │            │       │
        │  Docling   │ Docling    │ trafi │ heuristic
        │  (primary) │ (primary)  │ latura│ structurize
        │  ↓ fallback│ ↓ fallback │       │
        │ pymupdf4llm│ mammoth+md │       │
        └────┬───────┴────┬───────┴───┬───┘
             │            │           │
             │  SourceMeta carries (v1.0.2):
             │    organization, produced_by
             │    (split via heuristics.filter_organization)
             │
       structured-md  structured-md   text-md
             │            │           │
             └─────┬──────┴───────────┘
                   ▼
        ┌─────────────────────────┐
        │  pipeline/structured.py │   structured lane
        │  S1 figure caption pass │   (trusts layout)
        │  S2 table compactor     │
        │  S3 cite normalizer     │
        │  S4 heading hierarchy   │
        └────────────┬────────────┘
                     │
        ┌────────────┴────────────┐
        │     pipeline/text.py    │   text lane
        │  T1 line-wrap repair    │
        │  T2 dehyphenate         │
        │  T9 strip repeated      │   ◀ NEW v1.0.2
        │     byline              │
        │  T3 dedupe paragraphs   │
        │  T4 dedupe TOC block    │
        │  T7 dedupe TOC table    │   ◀ NEW v1.0.2
        │  T5 hdr/ftr strip       │
        │  T10 strip web          │   ◀ NEW v1.0.2
        │      fragments          │
        │  T6 list/code restore   │
        │  T8 strip cover         │   ◀ NEW v1.0.2
        │     artifacts           │
        └────────────┬────────────┘
                     │
        ┌────────────┴────────────┐
        │   pipeline/cleanup.py   │   shared lane
        │  C1 NFC normalize       │   (always last)
        │  C2 soft hyphen strip   │
        │  C3 ligature normalize  │
        │  C4 quote/dash normalize│
        │  C5 whitespace collapse │
        │  C8 decode HTML entities│   ◀ NEW v1.0.2
        │  C6 footnote marker strip│
        │  C7 validate            │
        └────────────┬────────────┘
                     │
                     │           ┌──────────────────────────┐
                     │           │   any2md/heuristics.py   │  ◀ NEW v1.0.2
                     │           │  pure functions:         │
                     │           │  - refine_title          │
                     │           │  - refine_abstract       │
                     │           │  - extract_authors       │
                     │           │    (+ optional arxiv API)│
                     │           │  - filter_organization   │
                     │           │  - is_arxiv_filename     │
                     │           │  - arxiv_lookup          │
                     │           └────────────┬─────────────┘
                     │                        │
                     ▼                        │
        ┌─────────────────────────┐           │
        │     frontmatter.py      │ ◀─────────┘   (consults heuristics
        │  - merge user overrides │                before YAML emission)
        │  - derive title/date/…  │
        │  - emit produced_by     │   ◀ NEW v1.0.2
        │  - compute content_hash │
        │  - emit YAML            │
        └────────────┬────────────┘
                     │
                     ▼
              <output>.md   ← frontmatter + cleaned body
```

The diagram captures three invariants that the rest of this document unpacks:
a converter produces raw markdown plus a `SourceMeta` and declares its lane;
the lane runs first, shared cleanup runs last, and `frontmatter.py` is the
only producer of the YAML block. v1.0.2 adds a fourth piece: a leaf
`heuristics.py` module of pure functions that `frontmatter.compose()`
consults to refine candidate field values before emission. Heuristics never
import from converters or pipeline modules — the dependency arrow points one
way, frontmatter to heuristics.

## Why two lanes

Different backends produce markdown of different trustworthiness. Docling's
output is structurally correct: tables are real GFM tables, multi-column
flow has been resolved, figures have captions, headings are at sensible
levels. The text-lane backends — pymupdf4llm fallback, trafilatura, mammoth,
the TXT heuristic — produce markdown that benefits from heavier regex repair.

The two lanes encode that distinction. Running the text-lane stages on
Docling output corrupts what Docling did right.

### Concrete damage example

This is what happens when the text-lane line-wrap repair (T1) runs on a
Docling-emitted GFM table:

Docling output (correct):
```markdown
| Quarter | Revenue | Cost |
|---------|---------|------|
| Q1 2026 | 4.2     | 2.1  |
| Q2 2026 | 4.8     | 2.3  |
```

After T1's heuristic incorrectly fires (incorrect, hypothetical):
```markdown
| Quarter | Revenue | Cost | |---------|---------|------| | Q1 2026 | 4.2     | 2.1  | | Q2 2026 | 4.8     | 2.3  |
```

T1 joins lines that don't end in terminal punctuation when the next line
starts lowercase. A pipe-delimited table row ends in `|`, not punctuation,
and a row that starts with `| Q1` starts with `|`, not an uppercase letter.
By the heuristic's letter, T1 should join — and that produces the corruption
above.

The actual T1 implementation guards against this with a structural-line check
(`_is_structural` recognizes table rows starting with `|`), but the broader
point is that a stage written for one input shape cannot be safely run on
the other. The two-lane separation makes that explicit at the architectural
level rather than relying on every stage to defensively detect every shape.

### Why shared cleanup is shared

The cleanup lane runs identically for both lanes. Its stages are lossless
normalizations that any well-formed markdown can absorb without harm:

- NFC unicode normalization
- soft hyphen removal
- ligature expansion (whitelist, not blanket NFKC)
- smart quote and ellipsis normalization
- whitespace collapse
- footnote-marker stripping (aggressive profile only)
- read-only validation

Centralizing these means `content_hash` is byte-deterministic: the same
post-cleanup body produces the same hash regardless of which lane ran first,
because the cleanup is the last thing that touched the bytes. This is the
determinism boundary the SSRM contract relies on.

## Stage catalog

Every stage is a pure `str → str` function with the signature:

```python
def stage(text: str, options: PipelineOptions) -> str: ...
```

Stages may emit non-fatal warnings via `pipeline.emit_warning()`, which the
runner collects. Stages must be no-ops on input they don't match: an
unmatched regex returns the input unchanged, never raises.

### Structured-lane stages (S1–S4 + lane-agnostic body cleanup)

Located in `any2md/pipeline/structured.py`. Run in the order listed before
shared cleanup, on Docling output.

| ID | Name | Lane | Input shape | Output shape | No-op cases | Edge cases |
|---|---|---|---|---|---|---|
| S1 | `lift_figure_captions` | structured | Markdown with `![alt](url)` images and HTML `<figure>...<figcaption>` blocks | Markdown with italic `*Figure: caption*` lines; image references kept only when `--save-images` | No images or figures present | Empty `alt` text drops the caption line entirely |
| S2 | `compact_tables` | structured | GFM tables with inconsistent per-cell padding | GFM tables with single-space cell padding; alignment row preserved | No table rows | Cells containing pipe-escaped content; alignment row identified by `^\|[\s:|-]+\|$` |
| S3 | `normalize_citations` | structured | Markdown with `[1] [2] [3]`-style spaced numeric citations | `[1][2][3]` (no spaces between adjacent numeric refs) | No spaced numeric citations | Non-numeric refs (`[Smith2020]`) are left alone |
| S4 | `enforce_heading_hierarchy` | structured | Markdown with any heading shape | Single H1, no skipped levels | Document has zero headings | First H1 absent: first heading promoted; subsequent H1s demoted to H2; H2 → H4 jump flattened to H2 → H3 → H4. Emits a warning when changes were applied. |

After S4, v1.0.3 appends four lane-agnostic stages from `text.py` so Docling
output gets the same body-cleanup pass that text-lane output already had:

| Run order | Name | Origin | Why also run on Docling |
|---|---|---|---|
| 5 | `strip_repeated_byline` (T9) | `text.py` | Academic PDFs that Docling extracts have the same `Author's Contact Information:` duplicate-byline pattern. |
| 6 | `dedupe_toc_table` (T7) | `text.py` | Docling renders the document's TOC as a leading GFM table that mirrors later H2/H3s — exactly the pattern T7 was written for. |
| 7 | `strip_cover_artifacts` (T8) | `text.py` | Cover-page noise (QR-code blurbs, version stamps) appears in Docling output too. |
| 8 | `strip_orphan_punctuation` | `text.py` (extracted from T10 in v1.0.3) | Docling's table parser occasionally emits malformed rows containing only `\|`. The trafilatura-specific short-fragment portion of T10 is *not* run on Docling — it would over-strip deliberate short headings. |

T10 `strip_web_fragments` itself stays text-lane-only.

### Text-lane stages (registered `text.py` stages: T1–T10)

Located in `any2md/pipeline/text.py`. The registered text-lane stages run
in the order listed in the `STAGES` list at the bottom of the module —
shown below. Note that the IDs (T1, T2, …) reflect the order each stage
was *introduced*, not the order they run in. The "Run order" column gives
the actual execution sequence.

In v1.0.3 the lone-`|`/`>` orphan-punctuation filter inside T10 was
extracted into a separate lane-agnostic helper `strip_orphan_punctuation`.
On the text lane, that helper is still invoked internally by T10, so it
does **not** appear as a standalone entry in `text.py`'s `STAGES` list.
The helper itself is registered separately in the structured lane's
`STAGES`, so Docling output gets the orphan-punctuation pass without
inheriting T10's trafilatura-specific short-fragment heuristic. See
`### Structured-lane stages` (above) for the v1.0.3 structured-lane
registrations.

| Run order | ID | Name | Lane | Input shape | Output shape | No-op cases | Edge cases |
|---|---|---|---|---|---|---|---|
| 1 | T1 | `repair_line_wraps` | text | Paragraph text with single newlines mid-sentence | Paragraphs joined into single lines per logical paragraph | Inside fenced code blocks; lines that are structural (lists, tables, headings); lines ending in terminal punctuation; next line starts with uppercase letter | Tracks fence state across the document; never joins across blank lines |
| 2 | T2 | `dehyphenate` | text | `co-\noperation`-style word breaks | `cooperation` when joined word appears elsewhere in the document | Joined word does not appear elsewhere (preserves genuine compounds) | Same-document corroboration only — no external wordlist |
| 3 | T9 | `strip_repeated_byline` | text | "Author's Contact Information:" / "Authors' Contact Information:" / "Contact:" lines duplicating an earlier byline; or email-list footer lines within the first 50 lines | Such lines (and any indented continuations) dropped | Profile is `conservative`; pattern not present | Aggressive/maximum only. Drops the matched line plus subsequent indented continuations. |
| 4 | T3 | `dedupe_paragraphs` | text | Paragraphs split by blank lines | Adjacent identical paragraphs collapsed to one | No adjacent duplicates | Whitespace-only differences are treated as identical (`.strip()` comparison) |
| 5 | T4 | `dedupe_toc_block` | text | TOC-shaped opening (≥ 5 entries matching `<title> <dots> <pagenum>`) followed by body whose H2/H3 headings cover ≥ 70% of the TOC entries | Text-formatted TOC block stripped | Profile is `conservative`; fewer than 5 TOC-shaped lines; overlap with body headings < 70% | Aggressive/maximum only |
| 6 | T7 | `dedupe_toc_table` | text | A leading GFM table (consecutive `|`-prefixed lines) in the first 30% of the document whose non-numeric cells match ≥ 70% of later H2/H3 headings | Such tables dropped | Profile is `conservative`; no table in the leading region; overlap below threshold; numeric cells dominate (looks like a data table, not a TOC) | Aggressive/maximum only. Sibling of T4 — handles table-formatted TOCs that T4's text-formatted heuristic misses (common on academic PDFs). |
| 7 | T5 | `strip_running_headers_footers` | text | Multi-page output with `\f` form-feed page breaks | Page-repeated headers and footers removed | Document has fewer than 3 pages; no form-feed markers; no line repeats ≥ 3 times | Also strips `Page N of M` and bare-numeric footer lines when they appear on ≥ 3 pages |
| 8 | T10 | `strip_web_fragments` | text | Lines containing only `\|` or `>` (delegated to `strip_orphan_punctuation` since v1.0.3); short incomplete-sentence lines (≤ 25 chars, no terminal punctuation) surrounded by blank lines and following a paragraph that ended in terminal punctuation | Fragments dropped | Profile is `conservative`; no qualifying fragments; line is a known short heading (`Contents`, `Note:`, etc.) | Aggressive/maximum only. Targets trafilatura extraction artifacts. Conservative on purpose — short legitimate lines are preserved. |
| 9 | T6 | `restore_lists_and_code` | text | ≥ 4-line indented blocks (4 leading spaces) between blank lines | Indented blocks wrapped in fenced code | Already inside a fence; block has < 4 non-empty lines | Tracks fence state; preserves leading 4-space indent strip when wrapping |
| 10 | T8 | `strip_cover_artifacts` | text | First ~30 lines (before the first H2): lines containing "QR code", "scan the", "customer feedback form" (case-insensitive); or lines matching `^(?:Third|Fourth|...) edition \d{4}-\d{2}$`; or lines matching `^Corrected version \d{4}-\d{2}$` | Such lines dropped | Profile is `conservative`; pattern not present; line is past the first H2 | Aggressive/maximum only. Bounded to the cover region so legitimate body content is never touched. |

### Shared cleanup stages (C1–C8)

Located in `any2md/pipeline/cleanup.py`. Run last, identically for both lanes.
The "Run order" column gives execution sequence; ID reflects introduction
order.

| Run order | ID | Name | Lane | Input shape | Output shape | No-op cases | Edge cases |
|---|---|---|---|---|---|---|---|
| 1 | C1 | `nfc_normalize` | shared | Any unicode text | NFC-normalized text | Already-NFC text | Required by SSRM `content_hash` invariant |
| 2 | C2 | `strip_soft_hyphens` | shared | Text containing U+00AD (`­`) | Text without U+00AD | No soft hyphens | Soft hyphens are invisible but token-costly |
| 3 | C3 | `normalize_ligatures` | shared | Text containing presentation-form ligatures (`ﬁ`, `ﬂ`, `ﬃ`, `ﬄ`, `ﬅ`, `ﬆ`, `ﬀ`) and NBSP | Text with whitelist-expanded ligatures and regular spaces | None of the whitelist characters present | Whitelist-only — does not run blanket NFKC, which would fold superscripts and CJK compatibility characters |
| 4 | C4 | `normalize_quotes_dashes` | shared | Smart quotes (`“”‘’`) and ellipsis (`…`) | Straight quotes (`""''`) and three-dot ellipsis | No smart quotes or ellipsis | En-dash and em-dash are preserved (semantic) |
| 5 | C5 | `collapse_whitespace` | shared | Multiple spaces, trailing whitespace, ≥ 3 blank lines | Single inter-word spaces, trimmed line ends, blank-line runs capped at 2 | None of those patterns present | Inter-word run regex requires non-space on both sides |
| 6 | C8 | `decode_html_entities` | shared | Body containing named (`&amp;`, `&lt;`, `&gt;`) or numeric (`&#x2014;`, `&#8212;`) HTML entities | Body with entities decoded via `html.unescape()` | No entities present; line is inside a fenced code block | Universal — runs at all profiles. Tracks fenced-code-block state to preserve literal entities inside ` ``` ` blocks. Inline single-backtick code is not skipped (false-positive rate acceptable). |
| 7 | C6 | `strip_footnote_markers` | shared | Body with inline footnote refs (`[^1]`, `¹`-`⁹`, `⁰`) followed by a recognizable footnotes section heading | Body without inline markers; footnotes section preserved | Profile is `conservative`; no footnotes heading found | Heading regex accepts `## Footnotes`, `## Notes`, `## References` (case-insensitive) |
| 8 | C7 | `validate` | shared | Any post-cleanup body | Identical body (read-only) | Always read-only | Emits warnings via `emit_warning()` for H1 count != 1, heading skips |

### Profile gating

`PipelineOptions.profile` controls a small subset of stages. The v1.0.2
text-lane additions (T7–T10) and the v1.0.2 cleanup addition (C8) follow the
same gating rules as their siblings.

| Profile | T4 TOC text dedupe | T7 TOC table dedupe | T8 cover artifacts | T9 repeated byline | T10 web fragments | `strip_orphan_punctuation` | C6 footnote markers | C8 HTML entities |
|---|---|---|---|---|---|---|---|---|
| `conservative` | off | off | off | off | off | off | off | on |
| `aggressive` (default) | on | on | on | on | on | on | on | on |
| `maximum` | on | on | on | on | on | on | on | on |

All other stages run unconditionally. C8 is on at every profile because HTML
entities in body text are universally wrong for both human and RAG readers —
there's no legitimate use case for keeping them un-decoded. The other gated
stages are aggressive-only because they apply heuristics that, while
high-precision in practice, carry a non-zero false-positive risk that the
conservative profile chooses to avoid.

## The `SourceMeta` dataclass

`SourceMeta` is the contract between converters and `frontmatter.compose()`.
A converter produces raw markdown plus a `SourceMeta`; `compose` reads
`SourceMeta` and the post-pipeline body to fill the frontmatter fields.
Defined in `any2md/frontmatter.py`:

```python
@dataclass
class SourceMeta:
    title_hint: str | None
    authors: list[str]
    organization: str | None
    produced_by: str | None       # NEW v1.0.2 — software/tool that produced
                                  # the source file (PDF Creator field;
                                  # DOCX docProps/app.xml Application field).
                                  # None when not extractable.
    date: str | None              # ISO-8601 YYYY-MM-DD
    keywords: list[str]
    pages: int | None             # PDFs only
    word_count: int | None        # DOCX/HTML/TXT (post-cleanup)
    source_file: str | None
    source_url: str | None
    doc_type: Literal["pdf", "docx", "html", "txt"]
    extracted_via: Literal[
        "docling", "pymupdf4llm", "mammoth+markdownify",
        "trafilatura", "trafilatura+bs4_fallback", "heuristic",
    ]
    lane: Lane
```

### Field-by-field

| Field | Filled by | Required for SSRM contract |
|---|---|---|
| `title_hint` | All converters when source metadata has a title (PDF `/Title`, DOCX `dc:title`, HTML `<title>`, otherwise `None`) | No — `frontmatter.derive_title` falls back to first H1, then filename |
| `authors` | PDF (`/Author` parsed), DOCX (`dc:creator`), HTML (`<meta name="author">`), TXT (always `[]`). v1.0.2 adds body-text extraction and an arxiv API enrichment via `heuristics.extract_authors`. | No — empty `[]` is valid |
| `organization` | PDF/DOCX `Company`, HTML `og:site_name`, otherwise `None`. v1.0.2 routes the PDF `Creator` field and DOCX `<Application>` element through `heuristics.filter_organization` so software values populate `produced_by` instead. | No — empty `""` is valid |
| `produced_by` | PDF `Creator` field (when it matches a known software pattern); DOCX `<Application>` element of `docProps/app.xml`; otherwise `None`. New in v1.0.2. | No — extension field |
| `date` | PDF `creationDate`, DOCX `dcterms:modified`, URL `Last-Modified` HEAD response, file mtime, today | Yes — derived to today if all sources fail |
| `keywords` | PDF `/Keywords`, DOCX `cp:keywords`, HTML `<meta name="keywords">`, trafilatura `categories`, otherwise `[]` | No — emitted only when non-empty |
| `pages` | PDF only (page count via `pymupdf.open`); other formats `None` | No — extension field |
| `word_count` | DOCX, HTML, TXT (whitespace-split count); PDF `None` | No — extension field |
| `source_file` | All file inputs; URL inputs `None` | No — extension field |
| `source_url` | URL inputs only; file inputs `None` | No — extension field |
| `doc_type` | All converters | Yes — emitted as `type` in the YAML |
| `extracted_via` | All converters | Yes — non-SSRM extension but required for traceability |
| `lane` | All converters | Yes — drives pipeline routing |

The four "required" fields above are required for the v1.0 contract to be
fillable, not for SSRM strict conformance. Strict SSRM has a different
required-fields list — see [output-format.md](output-format.md) for that
distinction.

### Where converters draw the data

| Format | `title_hint` | `authors` | `organization` | `date` | `keywords` |
|---|---|---|---|---|---|
| PDF (Docling) | PyMuPDF `metadata["title"]` | PyMuPDF `metadata["author"]` parsed | PyMuPDF `metadata["author"]` (fallback only) | PyMuPDF `metadata["creationDate"]` parsed | PyMuPDF `metadata["keywords"]` parsed |
| PDF (pymupdf4llm fallback) | Same as above | Same as above | Same as above | Same as above | Same as above |
| DOCX (Docling) | `docProps/core.xml dc:title` | `dc:creator` (split on common separators) | `docProps/app.xml Company` | `dcterms:modified` (truncated to YYYY-MM-DD) | `cp:keywords` split on commas |
| DOCX (mammoth fallback) | Same as above | Same as above | Same as above | Same as above | Same as above |
| HTML / URL | trafilatura `title` | trafilatura `author` (split on commas) | trafilatura `sitename` | trafilatura `date` for HTML; HTTP `Last-Modified` HEAD for URL | trafilatura `categories` |
| TXT | None (always falls back to filename or H1) | `[]` | None | file mtime | `[]` |

The DOCX converters parse `docProps/core.xml` and `docProps/app.xml` directly
via `zipfile + xml.etree.ElementTree`. There is no python-docx dependency.

## Heuristics module

`any2md/heuristics.py` (added in v1.0.2) is a leaf module of pure functions
that `frontmatter.compose()` and the converter modules consult to refine
candidate field values before they're emitted. It exists because the v0.7-
through-1.0.1 derivation rules — first H1 for title, source `/Author` for
authors, `Company` field for organization — were under-specified for several
real-world document classes (academic PDFs with cover pages, ISO standards
with boilerplate H1s, Wikipedia URL extractions with namespace prefixes).
The module collects the refinements in one place rather than scattering them
across the converters and the YAML emitter.

### Module boundary principle

`heuristics.py` does not import from `any2md/converters/` or
`any2md/pipeline/`. The dependency arrow points one way: converters and
`frontmatter.compose()` import from `heuristics`, never the reverse. This
keeps the module testable in isolation and avoids the temptation to chain
heuristics through pipeline state.

The single network-touching exception is `arxiv_lookup`, which uses
`urllib.request` from the stdlib (no new dependency) and emits a non-blocking
warning via the pipeline's existing `add_warnings` channel on any failure.
The SSRF guard reuses `_validate_url_host` from `any2md/converters/html.py`
via a lazy import inside the function body — that's the lone deferred import
in the module, present specifically to avoid the circular dependency.

### Public functions

| Function | Purpose | Profile-gated? |
|---|---|---|
| `filter_organization(creator_value)` | Splits a candidate `organization` value into either a real organization name or a `produced_by` software string. Returns an `OrgFilterResult(organization, produced_by)` named tuple where exactly one of the two is non-None. Used by PDF and DOCX converters. | No — pure pattern match |
| `refine_title(candidate, body, *, source_url, profile)` | Replaces a candidate title that looks like cover-page boilerplate (`"INTERNATIONAL STANDARD"`, `"TECHNICAL REPORT"`, etc.) with the first H2 in the body. Strips `Wikipedia:` namespace prefixes for `*.wikipedia.org` source URLs. Aggressive profile additionally splits DOCX line-broken titles (course code + project) when an explicit delimiter is present. | Conservative skips the DOCX line-break refinement |
| `refine_abstract(candidate, body, *, profile)` | Replaces a candidate abstract that looks like a byline, cover blurb, or TOC line with the first paragraph of the body's `## Abstract` (or `## Summary`) section. Decodes HTML entities, strips inline markdown links, truncates to ≤ 400 chars at the last sentence boundary. | Conservative returns `None` rather than falling back to a skipped paragraph |
| `extract_authors(body, title_hint, arxiv_id, *, arxiv_lookup_enabled, profile)` | Detects authors via a chain: (1) arxiv API lookup when an arxiv ID is set, (2) `Authors:` / `Author:` / `By` prefix lines, (3) academic byline pattern in the lines following the H1. Returns a deduplicated, order-preserving list capped at 20. | Conservative skips the byline-pattern inference (steps 1–3 only) |
| `is_arxiv_filename(name)` | Returns the arxiv ID if the filename matches `\d{4}\.\d{4,5}` (with optional `v\d+` version qualifier), otherwise `None`. Used by the PDF converter to gate `arxiv_lookup`. | No |
| `arxiv_lookup(arxiv_id, *, timeout=5.0)` | Single-attempt fetch from `https://export.arxiv.org/api/query?id_list={arxiv_id}`. Returns a dict of `{title, authors, abstract, date}` on success or `None` on any failure. SSRF-guarded; 5-second timeout; non-blocking warning on failure via `add_warnings`. | Disabled by `--no-arxiv-lookup` (CLI) or `PipelineOptions.arxiv_lookup=False` |

### Where each function is called

- **Converters (`pdf.py`, `docx.py`)** call `filter_organization` while
  building `SourceMeta`. PDF `_parse_pdf_metadata` routes the `/Creator`
  string; DOCX `_read_docx_metadata` routes the `<Application>` string.
  HTML and TXT converters do not call it — `sitename` from trafilatura and
  the absence of a producer in TXT mean there's nothing to filter.
- **`frontmatter.compose()`** calls `refine_title`, `refine_abstract`, and
  `extract_authors` after the body has been pipeline-cleaned but before
  YAML emission. Heuristic refinements never override an explicit user
  override (`--meta`, `.any2md.toml`); user values still win.
- **PDF converter** also calls `is_arxiv_filename` and passes the result to
  `extract_authors` via `SourceMeta`. The CLI flag `--no-arxiv-lookup` flips
  `PipelineOptions.arxiv_lookup` to `False`, which is then forwarded.

### Arxiv lookup contract

The arxiv lookup is opt-out, not opt-in: it runs by default for PDFs whose
filename matches the arxiv ID pattern. The rationale is that arxiv-named
PDFs typically have weak local metadata (the on-disk `/Author` field is
often empty or contains a single placeholder), and the arxiv API is the
canonical source. The contract is that any failure — DNS, timeout,
HTTP non-200, malformed XML, blocked SSRF check — emits a warning and
returns `None`. Conversion never fails because of network conditions.

For airgapped environments or hosts that must not make outbound calls,
`--no-arxiv-lookup` disables the lookup entirely. The flag does not affect
any other behavior; the rest of the pipeline runs identically.

## Adding a new converter

Adding support for a new input format means writing a `convert_<format>`
function and registering it in the dispatcher. The pattern is mechanical
because frontmatter and cleanup are not the converter's job — those are
centralized.

### Step 1: Create `any2md/converters/<format>.py`

The function signature follows the existing converters:

```python
from pathlib import Path

from any2md.frontmatter import SourceMeta, compose
from any2md.pipeline import PipelineOptions, run as pipeline_run
from any2md.converters import add_warnings, is_quiet
from any2md.utils import sanitize_filename


def convert_<format>(
    file_path: Path,
    output_dir: Path,
    options: PipelineOptions,
    force: bool = False,
) -> bool:
    """Convert a <format> file to a Markdown file in `output_dir`.

    Returns True on success, False on failure.
    """
    # 1. Produce raw markdown + SourceMeta from the source file.
    raw_md, meta = _extract(file_path, options)

    # 2. Run the pipeline (lane is part of `meta`).
    cleaned, warnings = pipeline_run(raw_md, meta.lane, options)
    add_warnings(warnings)

    # 3. Compose frontmatter + body.
    output = compose(cleaned, meta, options, overrides=options.frontmatter_overrides)

    # 4. Write to disk.
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / sanitize_filename(file_path.with_suffix(".md").name)
    if out_path.exists() and not force:
        # caller already handled skip; this is a defensive check
        return False
    out_path.write_text(output, encoding="utf-8", newline="\n")

    # 5. Print the per-file summary line (unless --quiet).
    if not is_quiet():
        print(f"  OK: {out_path.name}  ({meta.extracted_via}, {meta.lane}, ...)")
    return True
```

`_extract` is the format-specific code. It produces a `(markdown, SourceMeta)`
tuple. The lane assignment lives inside `_extract` because it's a property of
the backend, not of the file format.

### Step 2: Register in the dispatcher

Edit `any2md/converters/__init__.py`:

1. Add the new extension to `SUPPORTED_EXTENSIONS`.
2. Add a branch to `convert_file` that imports and calls `convert_<format>`.

```python
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".txt", ".<new>"}

def convert_file(file_path, output_dir, options=None, force=False, ...):
    ext = file_path.suffix.lower()
    if ext == ".<new>":
        from any2md.converters.<format> import convert_<format>
        return convert_<format>(file_path, output_dir, options=options, force=force)
    # existing branches...
```

The import is inside the branch — that's the lazy-import pattern any2md uses
to keep startup time low when most invocations don't touch every backend.

### Step 3: Decide the lane

The lane decision rests on whether the new backend produces layout-trustworthy
markdown.

- **Pick `"structured"`** if the backend already produces correctly-laid-out
  GFM tables, multi-column flow, and accurate heading levels (Docling-class
  output).
- **Pick `"text"`** if the backend's output benefits from line-wrap repair,
  paragraph dedupe, hyphenation fixes, or list/code restoration. This is the
  more common case for new backends.

A single backend can hand off to either lane depending on what it can handle
— see how the PDF converter selects between Docling (`"structured"`) and
pymupdf4llm (`"text"`). The lane is set per-conversion in `SourceMeta.lane`.

### Step 4: Tests

Three categories of test, as fixtures and assertions:

1. **Unit test for `_extract`.** Given a fixture file, assert the
   `SourceMeta` fields you populate (title hint, authors, lane,
   `extracted_via`).
2. **Integration test for the full converter.** Given a fixture file, run the
   converter end-to-end, parse the output frontmatter, assert key fields are
   populated and that the body is non-empty.
3. **Snapshot test.** Generate a golden output `.md` once, commit it under
   `tests/fixtures/snapshots/`, then assert byte-equality on subsequent
   runs. Update with `pytest --snapshot-update` when intentional changes
   land.

The constraint is that **the converter must produce raw markdown plus a
`SourceMeta` and declare a lane. Frontmatter and cleanup are not its job.**
Every existing converter follows this rule. New converters that try to
write frontmatter directly, or run cleanup before handing off, break the
single-emitter invariant that makes `content_hash` reproducible.

## Adding a new pipeline stage

Adding a stage means writing a function, registering it in a `STAGES` list,
and writing tests.

### Step 1: Pick the lane

| You're fixing... | Lane |
|---|---|
| An artifact specific to layout-trustworthy backends (e.g. Docling) | `pipeline/structured.py` |
| An artifact specific to text-lane backends (line wraps, hyphens, deduplication) | `pipeline/text.py` |
| A lossless, format-agnostic normalization (unicode, whitespace) | `pipeline/cleanup.py` |

When in doubt, prefer text-lane. Cleanup-lane stages must be lossless and
shape-agnostic — they run on every output regardless of backend, so any bug
or false positive shows up everywhere.

### Step 2: Write the function

The signature is `(text: str, options: PipelineOptions) -> str`. The function
must be a pure transformation — no I/O, no side effects beyond
`emit_warning()`.

```python
import re

from any2md.pipeline import emit_warning
# ... other imports

_SOMETHING_RE = re.compile(r"...", re.MULTILINE)


def fix_my_artifact(text: str, options: "PipelineOptions") -> str:
    """One-line description.

    Longer explanation: what artifact this fixes, what no-op cases look
    like, what edge cases were considered.
    """
    if not _SOMETHING_RE.search(text):
        return text
    # transform
    return _SOMETHING_RE.sub(replacement, text)
```

Naming: verbs in snake_case. Existing names follow the pattern `<verb>_<thing>`
(`repair_line_wraps`, `dehyphenate`, `compact_tables`, `normalize_citations`).
Match the style.

### Step 3: Register in the lane's `STAGES` list

At the bottom of the lane module, append the function to `STAGES`. Order
matters — stages run in list order. Place the new stage where it makes sense
in the existing flow:

```python
STAGES.append(fix_my_artifact)
```

For cleanup-lane stages, the list is constructed in one literal at the
bottom of `pipeline/cleanup.py`. Insert the function in the order it should
run, between existing stages.

### Step 4: Tests

One file per stage in `tests/unit/pipeline/test_<stage_name>.py`. At minimum:

- **Positive case.** Input that triggers the stage, expected output.
- **No-op case.** Input that doesn't match — assert output equals input.
- **Edge case.** A boundary condition (empty string, single character,
  multi-line, fence-aware behavior, etc.).

```python
from any2md.pipeline import PipelineOptions
from any2md.pipeline.text import fix_my_artifact

OPTIONS = PipelineOptions()


def test_fixes_known_artifact():
    text = "...input that triggers..."
    expected = "...expected output..."
    assert fix_my_artifact(text, OPTIONS) == expected


def test_noop_on_unrelated_input():
    text = "...input that should not match..."
    assert fix_my_artifact(text, OPTIONS) == text


def test_handles_edge_case():
    # describe the edge condition in the test name
    ...
```

If the stage emits warnings, also test that the right warning fires for the
right input. The pipeline runner exposes warnings via the second return value
of `pipeline.run`.

## Performance model

any2md's wall-clock time per file decomposes into three phases. Knowing
where time goes is the first step to deciding whether an optimization is
worth pursuing.

### Phase A: Backend extraction

This is where most time is spent for large or complex inputs.

| Backend | Typical time per page (PDF) or per file | Why |
|---|---|---|
| `docling` | 0.5–3 seconds per page | ML models for layout analysis and table structure recognition |
| `pymupdf4llm` | 0.05–0.2 seconds per page | C-level PDF parsing without ML inference |
| `mammoth+markdownify` | 0.1–0.5 seconds per file | XML parsing of DOCX zip + HTML-to-markdown conversion |
| Docling (DOCX) | 0.5–2 seconds per file | DOCX is parsed natively by Docling without OCR |
| `trafilatura` | 0.05–0.2 seconds per file | HTML parsing with boilerplate detection |
| TXT heuristic | < 0.05 seconds per file | Pure regex over text |

Docling is slower because it loads ML models (~2 GB on first use, cached
afterwards) and runs them per page. The model load is one-time per process;
the per-page inference dominates for multi-page documents.

For PDFs, the `pdf_looks_complex` heuristic (in `any2md/_docling.py`) runs a
fast PyMuPDF block-clustering pass (~50 ms) to decide whether to print an
install hint when Docling is missing. That heuristic only runs when Docling
is not available — the goal is to surface the install recommendation only
when it would actually help.

### Phase B: Pipeline stages

The pipeline operates on text only — no re-parsing, no re-rendering. All
stages are linear in body length. For a 100-page PDF on the Docling path,
total pipeline time is typically under 10% of Docling extraction time.

Per-stage cost is dominated by regex compile-and-match. Each stage uses
module-level pre-compiled patterns to avoid the per-call compile overhead.

T2 (`dehyphenate`) builds a set of words present in the document — it's
linear in word count, with one pass to build the set and one to check
candidates. T4 (`dedupe_toc_block`) builds a set of body H2/H3 titles —
likewise linear.

The contextvar-based warning emission (`emit_warning()`) has negligible
overhead; it's only called when a stage emits a warning, which is rare in
practice.

### Phase C: Frontmatter assembly

Frontmatter is computed once per file. The cost is one SHA-256 over the body
(`compute_content_hash`), one regex pass for H1 / H2 detection
(`extract_abstract`, `recommend_chunk_level`), and a YAML-emit pass that's
linear in the number of fields. For a typical document, this phase is under
50 ms.

### Where the optimization opportunities are

In rough order of impact:

1. **Docling model warmup.** First-invocation latency includes 2–10 seconds
   of model load. For batch conversions, this is amortized; for single-file
   invocations, it dominates. A long-running daemon that holds Docling open
   between conversions would eliminate this. Out of scope for v1.0 (the
   project is a CLI, not a service).
2. **Parallel batch processing.** Currently sequential. Adding multiprocess
   parallelism for batch mode would scale linearly with cores for the
   pymupdf4llm path; for the Docling path, GPU contention may limit
   speedup.
3. **Pipeline stage fusion.** Stages that operate line-by-line could in
   principle be combined into a single pass. The current architecture
   prioritizes testability (one stage = one tested transformation) over
   raw speed; this trade-off is intentional.
4. **PDF complexity heuristic.** The 50ms cost of `pdf_looks_complex` is
   wasted when Docling is installed (the result is unused). Skipping the
   call when `has_docling()` returns true would save the cost; the savings
   are small per file but multiply across batches.

The pipeline is not the bottleneck for any backend except possibly the TXT
heuristic, where extraction is so fast that pipeline stages dominate.
Optimization effort is best spent on Phase A (extraction) for typical
workloads.

## Cross-references

- [README](../README.md) — the top-level orientation.
- [output-format.md](output-format.md) — the output shape this pipeline
  produces.
- [cli-reference.md](cli-reference.md) — the flags that drive
  `PipelineOptions`.
- [troubleshooting.md](troubleshooting.md) — symptom-cause-fix when the
  pipeline produces unexpected output.
- [upgrading-from-0.7.md](upgrading-from-0.7.md) — what changed in the
  pipeline shape between v0.7 and v1.0.
