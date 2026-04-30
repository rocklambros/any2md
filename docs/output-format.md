# Output format

This document is the contract for the Markdown that any2md writes. If you
consume any2md output downstream — feeding it to an embedding model, a chunker,
a vector store, or a custom retrieval pipeline — this is the file that tells
you exactly what fields you can rely on, how they're derived, and how to
validate that an output file hasn't been tampered with after generation.

For a high-level orientation, see the [README](../README.md). For the
underlying implementation, see [architecture.md](architecture.md). For a
flag-by-flag CLI reference, see [cli-reference.md](cli-reference.md).

## Why a contract

A retrieval pipeline ingests documents from many shapes (PDF, DOCX, HTML, plain
text) and turns each into chunks, embeddings, and metadata records that the
retriever and the generation step both consume. The pipeline runs in stages
that are usually owned by different code paths — extraction, normalization,
chunking, embedding, indexing, and finally retrieval at query time. Each stage
either reads or writes the metadata around a chunk: the source filename, a
stable ID, a generation date, a hash for cache invalidation. When those
metadata fields appear in different shapes for different source formats, every
downstream stage has to learn every shape. That coupling is the cost of
ad-hoc converters.

A documented frontmatter contract removes that cost. The chunker can rely on
`recommended_chunk_level` being either `"h2"` or `"h3"`. The cache can rely on
`content_hash` being a 64-character lowercase hex SHA-256 over the
NFC-normalized body. The retrieval result formatter can rely on `title` being
non-empty, single-line, and YAML-escaped. None of those guarantees come free —
they exist because every any2md output goes through the same final emitter and
because every field in this document has a derivation rule that's tested.

## The SAGE connection

any2md's frontmatter is **SAGE-compatible**. SAGE (Structured Security
Reasoning Markdown) is a documented schema for LLM-consumable security
research documents — its primary audience is producers of threat intelligence
and security guidance who want a stable shape for downstream RAG and LLM
analysis. SAGE v1.0-RC1 is the version this contract tracks.

"Compatible" rather than "strict" because most documents any2md converts are
not security research. SAGE has fields with controlled vocabularies —
`document_type`, `content_domain`, `tlp`, `frameworks_referenced` — that don't
have plausible defaults for an arbitrary PDF or web page. Strict SAGE
validators reject empty or unknown values for those fields. any2md's choice is
to emit the fields with empty defaults (`""` or `[]`) and `status: "draft"`, so
the output is machine-readable in the SAGE shape but doesn't claim to be a
finished SAGE document. If you produce real SAGE-conforming security research,
populate those fields explicitly via [`--meta` or `.any2md.toml`](cli-reference.md#configuration-meta-and-meta-file).

The fields below are grouped: identity, classification, provenance, integrity,
optional, then any2md extension fields retained from v0.7 for traceability.
This is the order they appear in the YAML block.

v1.0.2 added one extension field, `produced_by`, between `extracted_via` and
`pages`. It's documented in its own subsection below and listed alongside the
other any2md extension fields.

## Field-by-field reference

Each field carries: a one-line meaning, a type, a derivation rule, what
"empty" looks like, an example value, and (where it matters) a common-mistake
callout. Fields marked **auto** are derived by any2md from the source
document. Fields marked **opt-in** are derived only when a flag or config
explicitly requests it. Fields marked **user** are empty unless you set them
via `--meta`, `--meta-file`, or `.any2md.toml`.

### `title`

**auto** | type: `string` (non-empty)

**Derivation:** First H1 in the post-pipeline body, with leading `#` and
emphasis markers stripped. Falls back, in order, to the source document's
title metadata (PDF `/Title`, DOCX `dc:title`, HTML `<title>` via
trafilatura), then to the source filename with the extension removed and
underscores converted to spaces. Never empty — the fallback is guaranteed to
produce a non-empty string.

**Example:** `"Quarterly Financial Report"`

**Common mistake:** Editing the H1 in the body after generation invalidates
`content_hash` (see below) but does not change `title` in the frontmatter,
because the frontmatter is written once and then static. Re-run any2md if you
edit the H1.

### `document_id`

**opt-in** | type: `string` (empty by default)

**Derivation:** Empty string `""` unless `--auto-id` is passed. With
`--auto-id`, generated as `{PREFIX}-{YYYY}-{TYPE}-{SHA8}` where `SHA8` is the
first 8 hex characters of `content_hash`, `YYYY` is the current year, and
`PREFIX` / `TYPE` default to `LOCAL` / `DOC`. Override the prefix and type via
`[document_id]` in `.any2md.toml`.

**Example empty:** `""`
**Example with `--auto-id`:** `"LOCAL-2026-DOC-a3f1c91d"`

**Common mistake:** Treating `document_id` as a primary key without the
publisher prefix. The same body converted by two different organizations both
using the default `LOCAL` prefix will collide. Set
`[document_id].publisher_prefix` in your `.any2md.toml` to a value unique to
your organization.

### `version`

**auto** | type: `string`

**Derivation:** Always `"1"` for v1.0. Reserved as a string so future revisions
can use semantic version-style values without breaking the type.

**Example:** `"1"`

### `date`

**auto** | type: `string` (ISO-8601 `YYYY-MM-DD`)

**Derivation:** From source-side metadata where available, then today's date.
For local files, the file `mtime`. For URL fetches, the HTTP `Last-Modified`
header (single best-effort HEAD request after the SSRF check passes); falls
back to today on HEAD failure. For PDFs and DOCX, parsed from the embedded
`creation` / `modified` properties when present. For TXT files without an
mtime, today.

**Example:** `"2026-04-01"`

**Common mistake:** Assuming `date` is the date the document was *converted*.
It's the date the *source* was last modified. Track conversion time separately
if you need it (it's not in the frontmatter; the file's own mtime on disk
records when any2md wrote it).

### `status`

**auto** | type: `string` (controlled vocabulary)

**Derivation:** Always `"draft"` for converted documents. SAGE allows
non-controlled-vocab values for other fields when `status` is `"draft"`, which
is why this is the default — it's how an any2md output declares "I have an
SAGE-compatible shape but I have not been authored as SAGE."

**Example:** `"draft"`

**Common mistake:** Overriding to `"published"` via `--meta` for documents
that haven't actually been reviewed. SAGE consumers may treat
`status: "published"` as a signal that the controlled-vocabulary fields are
trustworthy. Don't claim a status the content doesn't earn.

### `document_type`

**user** | type: `string` (controlled vocabulary or empty)

**Derivation:** Empty `""` by default. SAGE defines a controlled vocabulary
(e.g. `"guidance"`, `"vuln_advisory"`, `"threat_report"`) but any2md cannot
infer it from a generic document.

**Example empty:** `""`
**Example user-set:** `"guidance"`

### `content_domain`

**user** | type: `array<string>`

**Derivation:** Empty `[]` by default. SAGE controlled vocabulary
(e.g. `"ai_security"`, `"cloud"`, `"identity"`).

**Example empty:** `[]`
**Example user-set:** `["ai_security", "supply_chain"]`

### `authors`

**auto** | type: `array<string>` (may be empty)

**Derivation:** From source-side metadata when extractable. PDF `/Author`,
DOCX `dc:creator`, HTML `<meta name="author">` (via trafilatura). The PDF
extractor splits on common separators (`,`, `;`, ` and `, ` & `). Always an
array even if there's a single author.

**Example empty:** `[]`
**Example single:** `["Jane Smith"]`
**Example multiple:** `["Jane Smith", "Bob Jones"]`

**Common mistake:** Setting `--meta authors=Alice` produces a string, not an
array. Use the comma-array syntax: `--meta authors="Alice, Bob"` or, in
`.any2md.toml`, `authors = ["Alice"]`.

### `organization`

**auto** | type: `string`

**Derivation:** PDF/DOCX `Company` field; HTML `og:site_name` via trafilatura;
otherwise empty. User overrides commonly set this for corpus-wide attribution.

**Example empty:** `""`
**Example user-set:** `"Cloud Security Alliance"`

### `generation_metadata`

**auto** | type: `object` (`{authored_by: string}` minimum)

**Derivation:** Always emitted with `authored_by: "unknown"` because any2md
converts content; it does not author it. SAGE's `generation_metadata` block
exists to record who or what produced the document (a human, a model, a
collaboration). If you ran any2md as part of an authoring workflow, override
the value via `--meta generation_metadata.authored_by=human`.

**Example default:**
```yaml
generation_metadata:
  authored_by: "unknown"
```

**Example user-set:**
```yaml
generation_metadata:
  authored_by: "human_ai_collaborative"
  model_id: "claude-opus-4-7"
```

**Common mistake:** Adding fields under `generation_metadata` and expecting
SAGE validators to accept them. The SAGE schema for this block has its own
shape — consult the SAGE specification before adding non-standard subfields.

### `content_hash`

**auto** | type: `string` (64-char lowercase hex)

**Derivation:** SHA-256 of the post-pipeline body, after NFC normalization
and LF line ending conversion. The body that's hashed is exactly the body
that's written to disk. See [`content_hash` semantics](#content_hash-semantics)
below for the exact recipe.

**Example:** `"a3f1c91dca7e4b6f9c2e0d8b1f4a7e2c5d3b9f0a1c4e7d2b5f8a3c6e9d2b5f8a"`

**Common mistake:** Comparing `content_hash` across runs of two different
versions of any2md. Cleanup-stage changes between versions can produce
byte-different output for the same input, which produces a different hash by
design — that's how you know the cleanup changed.

### `keywords`

**auto, conditional** | type: `array<string>`

**Derivation:** PDF `/Keywords` (split on commas), DOCX `cp:keywords`, HTML
`<meta name="keywords">`, trafilatura `categories`. Emitted only when at
least one keyword was extracted; the field is omitted entirely from the YAML
block when empty.

**Example present:**
```yaml
keywords:
  - alignment
  - LLM safety
```
**Example absent:** (the field key is not present in the frontmatter at all)

### `token_estimate`

**auto** | type: `integer`

**Derivation:** `ceil(len(body) / 4)`. A four-characters-per-token rough rule.
Not a tokenizer-exact count and intentionally so — relying on `tiktoken` or a
model-specific tokenizer would couple the converter to a specific embedding
model. Use this field for rough budget arithmetic, not for hard cost
calculations.

**Example:** `18420`

### `recommended_chunk_level`

**auto** | type: `string` (`"h2"` or `"h3"`)

**Derivation:** `"h3"` if any H2 section's body has a `token_estimate` greater
than 1500. Otherwise `"h2"`. The threshold is tuned so chunks fit comfortably
inside a 4K context window after metadata overhead.

**Example:** `"h2"` or `"h3"`

See [Chunking guidance](#chunking-guidance) below for the reasoning behind the
threshold and how to use this field in a chunker.

### `abstract_for_rag`

**auto, conditional** | type: `string` (≤ 400 chars)

**Derivation:** First non-heading paragraph of ≥ 80 characters after the H1,
truncated at the last sentence boundary at or before 400 characters. Emitted
only when `token_estimate ≥ 500` — short documents don't need an abstract for
retrieval. The field key is omitted entirely when not emitted.

**Example present:** `"This paper investigates whether current safety-alignment techniques in commercial LLMs withstand adversarial probing in the COMP4441 final-project context. Methods, metrics, and limitations are described."`
**Example absent:** (the field key is not present in the frontmatter)

**Common mistake:** Treating `abstract_for_rag` as a summary. It's the
first qualifying paragraph, not a model-generated synopsis. If the source
document doesn't begin with a clear lead paragraph, this field will reflect
that.

### `frameworks_referenced`, `tlp`

**user** | type: `array<string>` and `string`

**Derivation:** Empty by default. SAGE-specific fields (security frameworks
the document references; traffic-light-protocol marking). User-supplied via
`--meta` or `.any2md.toml`.

**Example user-set:**
```yaml
frameworks_referenced:
  - OWASP_LLM_TOP10
  - NIST_AI_RMF
tlp: "TLP:CLEAR"
```

### `source_file`, `source_url`

**auto, conditional** | type: `string`

**Derivation:** any2md extension fields, retained from v0.7 for traceability.
`source_file` is the original filename for local file inputs; `source_url` is
the original URL for URL inputs. Mutually exclusive — only one is emitted per
document.

**Example file:** `source_file: "report.pdf"`
**Example URL:** `source_url: "https://example.com/article"`

### `type`

**auto** | type: `string` (`"pdf"`, `"docx"`, `"html"`, `"txt"`)

**Derivation:** Source format. any2md extension field.

**Example:** `"pdf"`

### `extracted_via`

**auto** | type: `string`

**Derivation:** Records which backend produced the raw markdown.

| Value | When |
|---|---|
| `"docling"` | PDF or DOCX with `[high-fidelity]` extras installed |
| `"pymupdf4llm"` | PDF without Docling |
| `"mammoth+markdownify"` | DOCX without Docling |
| `"trafilatura"` | HTML or URL (primary path) |
| `"trafilatura+bs4_fallback"` | HTML when trafilatura returns no content |
| `"heuristic"` | TXT files (any2md's heuristic structurizer) |

This field is what tells you, looking at an output file in isolation, why two
otherwise-similar inputs produced different output shapes.

### `produced_by`

**auto, conditional** | type: `string` (any2md extension field, new in v1.0.2)

**Derivation:** Software that produced the source file. Distinct from
`extracted_via`, which records the any2md backend that produced the markdown
— `produced_by` records the upstream tool that produced the *source*.

| Source | Where the value comes from |
|---|---|
| PDF | The `/Creator` metadata field, after passing through `heuristics.filter_organization`. Software-pattern matches (LaTeX, acmart, Adobe InDesign, Microsoft Word, Pandoc, etc.) populate `produced_by`; non-software values populate `organization` instead. |
| DOCX | The `<Application>` element of `docProps/app.xml`. Routed through the same `filter_organization` check. The `<Company>` element (a real organization) takes priority over `<Application>` for the `organization` field. |
| HTML / URL | Not populated; trafilatura's `sitename` is treated as a real site, not software. |
| TXT | Not populated; the format does not expose a producer. |

The field is omitted from the frontmatter when empty. When the source was
created by a real organization (and therefore `organization` is populated),
`produced_by` will typically be empty; when the source was produced by
software (LaTeX, Word, InDesign), `organization` will typically be empty and
`produced_by` will hold the software string.

This field exists because the v0.7-era behavior of dumping the PDF `/Creator`
software string into `organization` was wrong: a value like
`"LaTeX with acmart 2024/08/25 v2.09 …"` is not the document's organization.
v1.0.2 separates the two, so downstream consumers that key on `organization`
get a real organization name (or `""`) and never see software junk there.

**Example values:**
- `"LaTeX with acmart 2024/08/25 v2.09 ..."`
- `"Adobe InDesign 16.2 (Windows)"`
- `"Microsoft® Word for Microsoft 365"`
- `"Pandoc 3.1"`

**Example empty:** field is omitted from the YAML block.

### `pages`, `word_count`

**auto, conditional** | type: `integer`

**Derivation:** any2md extension fields. `pages` is set for PDFs only.
`word_count` is set for DOCX, HTML, and TXT (post-cleanup body word count via
whitespace splitting). Both are omitted entirely when not set.

## The body shape

The body is everything after the `---` line that closes the frontmatter. It
follows three rules.

### Single H1

Exactly one H1 (`# Heading`) per document. The pipeline's S4 stage promotes the
first heading to H1 if no H1 was present in the source, and demotes any
subsequent H1s to H2. This rule is what makes downstream chunkers and titlers
work reliably.

### No skipped levels

Heading levels never skip. An H2 followed by an H4 in the source is rewritten
to H2 → H3 → H4. A skip emits a non-fatal validator warning during conversion
(visible in stderr; promoted to a non-zero exit by `--strict`).

### Citations

Adjacent numeric citations are coalesced: `[1] [2] [3]` becomes `[1][2][3]`.
This is a presentational normalization — it does not change which sources are
referenced, only how the references appear inline.

### Tables

Tables use GFM (GitHub-Flavored Markdown) pipe syntax with a header row and
an alignment row. Per-cell padding is normalized to a single space inside the
pipes. Example after normalization:

```markdown
| Column A | Column B |
|----------|----------|
| value 1  | value 2  |
```

The structured-lane S2 stage strips inconsistent padding so the rendering is
uniform across rows.

### Footnote markers

Inline footnote markers like `[^1]`, `¹`, and similar are stripped from the
body when a recognizable footnotes section heading exists later in the
document and the profile is `aggressive` or `maximum`. The footnotes section
itself is preserved. Footnote stripping is intentionally aggressive because
markers in inline body text consume tokens and rarely contribute to retrieval.

### Worked example

Source TXT input:

```text
SAFETY ALIGNMENT IN LLMS

This brief paper covers three points. First we describe the
methodology. Second we present results. Third we discuss
implications.

METHODOLOGY

We tested fourteen models...
```

any2md output (frontmatter elided for brevity):

```markdown
---
title: "Safety Alignment In LLMs"
...
content_hash: "<sha256>"
token_estimate: 42
recommended_chunk_level: "h2"
type: "txt"
extracted_via: "heuristic"
---

# Safety Alignment In LLMs

This brief paper covers three points. First we describe the methodology.
Second we present results. Third we discuss implications.

## Methodology

We tested fourteen models...
```

Note the line-wrap repair joining "the\nmethodology" into one line, the
ALL-CAPS heading promoted to a real H1, and the second-level heading recognized
as H2.

## `content_hash` semantics

`content_hash` is the integrity check for an any2md output. It exists so
downstream caches, RAG indexes, and code-review tools can answer one question:
"is the body of this file byte-identical to what any2md wrote?"

### Normalization recipe

The hash is computed over the body (everything after the closing `---\n` of the
frontmatter, plus the blank-line separator any2md inserts). The body is
normalized in two ways before hashing:

1. **Line endings.** All `\r\n` and bare `\r` are converted to `\n`.
2. **Unicode form.** The string is normalized to NFC
   (`unicodedata.normalize("NFC", text)`).

Then SHA-256 is computed over the UTF-8 encoded bytes. The resulting digest is
written as a lowercase hex string in the `content_hash` field.

The canonical implementation is `any2md.frontmatter.compute_content_hash`.

### Recomputing the hash

This snippet recomputes `content_hash` from a written `.md` file and compares
it against the value embedded in the frontmatter. It runs against any v1.0
output, requires only the standard library, and matches the canonical
implementation:

```python
import hashlib
import re
import unicodedata
from pathlib import Path

text = Path("output.md").read_text(encoding="utf-8")
# Frontmatter sits between two '---\n' markers at the start.
# Split into [pre-frontmatter, frontmatter, body]; pre is empty.
_, frontmatter, body = text.split("---\n", 2)
# any2md inserts a blank line after the closing '---' before the body.
if body.startswith("\n"):
    body = body[1:]

body = body.replace("\r\n", "\n").replace("\r", "\n")
body = unicodedata.normalize("NFC", body)
recomputed = hashlib.sha256(body.encode("utf-8")).hexdigest()

stored = re.search(r'^content_hash:\s*"([0-9a-f]+)"', frontmatter, re.MULTILINE).group(1)
assert recomputed == stored, f"hash mismatch: {recomputed} != {stored}"
```

If the assertion fails, the body of `output.md` was edited after any2md wrote
it, or the file was saved through an editor that converted line endings to
CRLF. Either re-run any2md or run `dos2unix output.md` to restore LF line
endings.

### What changes the hash, what doesn't

Any change to the body changes the hash. Any change to the frontmatter — even
fields like `title` or `date` that are written based on the body — does not
change the hash. The frontmatter is metadata *about* the body and is not part
of the hash input. This is intentional: it lets you set custom frontmatter
overrides via `--meta` without invalidating downstream caches that key on the
body content.

## Chunking guidance

`recommended_chunk_level` exists to give a chunker a reasonable default when
splitting a document for retrieval. The two values trade off in concrete ways.

### `recommended_chunk_level: "h2"`

You'd split the document on H2 boundaries. Each H2 section becomes one chunk.
This is the default for documents whose H2 sections all fit comfortably inside
a 4K context window (estimated body ≤ 1500 tokens per H2).

For a 10K-token doc with five H2 sections, h2 chunks average 2K tokens each.
Retrieval gets a coherent topic per chunk and the LLM has enough context to
answer questions that span paragraphs within one section.

The latency/recall tradeoff: fewer, larger chunks mean fewer embedding
computations at index time, fewer index entries to search, and higher recall
per chunk because more context is included. The cost is precision — a query
that matches one paragraph inside a 2K-token chunk also retrieves the rest of
that section.

### `recommended_chunk_level: "h3"`

You'd split on H3 boundaries. Each H3 (or each H2 section that has no H3
children) becomes one chunk. This is the recommendation for documents with at
least one H2 section larger than 1500 estimated tokens.

For a 30K-token doc with three H2 sections (10K each), h2 chunks would exceed
typical context budgets. h3 chunks bring the average back to 1–2K tokens.

The latency/recall tradeoff inverts: more, smaller chunks mean more embedding
computations and a larger index, but better precision because each chunk
covers a narrower topic.

### Using the field in a chunker

Pseudocode:

```python
import yaml

def chunk(md_text):
    fm_text, body = md_text.split("---\n", 2)[1:]
    fm = yaml.safe_load(fm_text)
    level = fm["recommended_chunk_level"]
    pattern = f"\n{'#' * (2 if level == 'h2' else 3)} "
    return [c for c in body.split(pattern) if c.strip()]
```

This is the simplest possible heading-split chunker. Production chunkers
typically also enforce a minimum and maximum token budget per chunk on top of
the heading split — `recommended_chunk_level` gives the *boundary*, not the
*size*.

### Override

The recommendation is a heuristic. Your retrieval evaluation (recall@k,
precision@k, or LLM-as-judge scores on held-out queries) should make the final
decision. If you measure better retrieval at h2 even when any2md recommends
h3, override; the field is a starting point.

## Validating output programmatically

`any2md.validators` exposes two checks for downstream consumers.

### Heading hierarchy

```python
from any2md.validators import check_heading_hierarchy

with open("output.md") as f:
    text = f.read()
body = text.split("---\n", 2)[2]

issues = check_heading_hierarchy(body)
if issues:
    for issue in issues:
        print(f"warning: {issue}")
```

`check_heading_hierarchy` returns a list of human-readable strings describing
hierarchy issues. The empty list means the body is clean. It catches two
classes of issue: H1 count not exactly 1, and any heading that skips levels
(e.g. H2 → H4). any2md's own pipeline runs this check during conversion (the
C7 stage) and emits warnings; this function lets you re-run the check on a
written file.

### `content_hash` round-trip

```python
import re
from any2md.validators import check_content_hash_round_trip

with open("output.md") as f:
    text = f.read()
parts = text.split("---\n", 2)
fm, body = parts[1], parts[2].lstrip("\n")
expected = re.search(r'^content_hash:\s*"([0-9a-f]+)"', fm, re.MULTILINE).group(1)

ok = check_content_hash_round_trip(body, expected)
if not ok:
    print("hash mismatch — body has been edited or line endings changed")
```

`check_content_hash_round_trip` returns `True` when the recomputed hash matches
the expected value. Use this in CI gates that verify a corpus hasn't been
tampered with after generation.

## JSON Schema

This schema describes the v1.0 frontmatter block. Conditional fields
(`keywords`, `abstract_for_rag`, `pages`, `word_count`, `source_file`,
`source_url`, `produced_by`) are documented here as optional; they're omitted
from the frontmatter when not set. SAGE-only fields a user might add (`tlp`,
`frameworks_referenced`, etc.) are listed as additional valid fields.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/rocklambros/any2md/output-frontmatter-v1.json",
  "title": "any2md v1.0 frontmatter",
  "type": "object",
  "required": [
    "title",
    "document_id",
    "version",
    "date",
    "status",
    "document_type",
    "content_domain",
    "authors",
    "organization",
    "generation_metadata",
    "content_hash",
    "token_estimate",
    "recommended_chunk_level",
    "type",
    "extracted_via"
  ],
  "additionalProperties": true,
  "properties": {
    "title": {
      "type": "string",
      "minLength": 1
    },
    "document_id": {
      "type": "string",
      "description": "Empty by default; non-empty when --auto-id is used.",
      "pattern": "^$|^[A-Z][A-Z0-9]*-[0-9]{4}-[A-Z][A-Z0-9]*-[0-9a-f]{8}$"
    },
    "version": {
      "type": "string"
    },
    "date": {
      "type": "string",
      "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
    },
    "status": {
      "type": "string",
      "enum": ["draft", "published", "deprecated"]
    },
    "document_type": {
      "type": "string"
    },
    "content_domain": {
      "type": "array",
      "items": { "type": "string" }
    },
    "authors": {
      "type": "array",
      "items": { "type": "string" }
    },
    "organization": {
      "type": "string"
    },
    "generation_metadata": {
      "type": "object",
      "required": ["authored_by"],
      "properties": {
        "authored_by": { "type": "string" },
        "model_id": { "type": "string" }
      },
      "additionalProperties": true
    },
    "content_hash": {
      "type": "string",
      "pattern": "^[0-9a-f]{64}$"
    },
    "keywords": {
      "type": "array",
      "items": { "type": "string" }
    },
    "frameworks_referenced": {
      "type": "array",
      "items": { "type": "string" }
    },
    "tlp": {
      "type": "string",
      "enum": ["", "TLP:CLEAR", "TLP:GREEN", "TLP:AMBER", "TLP:AMBER+STRICT", "TLP:RED"]
    },
    "token_estimate": {
      "type": "integer",
      "minimum": 0
    },
    "recommended_chunk_level": {
      "type": "string",
      "enum": ["h2", "h3"]
    },
    "abstract_for_rag": {
      "type": "string",
      "maxLength": 400
    },
    "source_file": {
      "type": "string"
    },
    "source_url": {
      "type": "string",
      "format": "uri"
    },
    "type": {
      "type": "string",
      "enum": ["pdf", "docx", "html", "txt"]
    },
    "extracted_via": {
      "type": "string",
      "enum": [
        "docling",
        "pymupdf4llm",
        "mammoth+markdownify",
        "trafilatura",
        "trafilatura+bs4_fallback",
        "heuristic"
      ]
    },
    "produced_by": {
      "type": "string",
      "description": "Software that produced the source file (PDF Creator, DOCX Application). New in v1.0.2; omitted when empty."
    },
    "pages": {
      "type": "integer",
      "minimum": 1
    },
    "word_count": {
      "type": "integer",
      "minimum": 0
    }
  }
}
```

The schema sets `additionalProperties: true` because users add fields via
`--meta` and `.any2md.toml` that are not part of the v1.0 contract. A stricter
schema for SAGE-conforming outputs would set this to `false` and add the SAGE
controlled-vocabulary constraints to `document_type`, `content_domain`, and
related fields. Use this schema as a starting point for downstream validation
and tighten it for your environment.

## Cross-references

- [README](../README.md) — orientation, install, and usage by source type.
- [cli-reference.md](cli-reference.md) — flags that affect frontmatter
  derivation (`--auto-id`, `--meta`, `--meta-file`, `--profile`).
- [architecture.md](architecture.md) — the pipeline stages whose output the
  frontmatter describes.
- [troubleshooting.md](troubleshooting.md) — `content_hash` mismatch
  diagnosis.
- [upgrading-from-0.7.md](upgrading-from-0.7.md) — v0.7 frontmatter shape
  mapped to v1.0.
