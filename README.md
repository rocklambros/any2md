# any2md

Convert PDF, DOCX, and HTML files — or web pages by URL — to clean, LLM-optimized Markdown with YAML frontmatter.

One command. Any format. Consistent, structured output ready for language models.

## Quick Start

```bash
pip install any2md

any2md report.pdf
any2md https://example.com/article
any2md --help
```

Output lands in `./Text/` by default:

```markdown
---
title: "Quarterly Financial Report"
source_file: "report.pdf"
pages: 12
type: pdf
---

# Quarterly Financial Report

Document content here...
```

## Features

| Feature | Description |
|---------|-------------|
| **Multi-format** | PDF, DOCX, HTML (.html, .htm) |
| **URL fetching** | Pass any http/https URL as input |
| **YAML frontmatter** | Title, source, page/word count, type |
| **Batch processing** | Single file, directory scan, or mixed inputs |
| **Auto-routing** | Dispatches to the correct converter by extension |
| **Smart skip** | Won't overwrite existing files unless `--force` |
| **Filename sanitization** | Spaces, special characters, unicode dashes handled |
| **Title extraction** | Pulls the first H1–H3 heading automatically |
| **Link stripping** | `--strip-links` removes hyperlinks, keeps text |

## Installation

Requires **Python 3.8+**.

```bash
pip install any2md
```

### From source

```bash
git clone https://github.com/rocklambros/any2md.git
cd any2md
pip install .
```

### Dependencies

| Library | Purpose |
|---------|---------|
| [PyMuPDF](https://pymupdf.readthedocs.io/) + [pymupdf4llm](https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/) | PDF extraction |
| [mammoth](https://github.com/mwilliamson/python-mammoth) + [markdownify](https://github.com/matthewwithanm/python-markdownify) | DOCX conversion |
| [trafilatura](https://trafilatura.readthedocs.io/) + [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) | HTML/URL extraction |

## Usage

### Basic conversion

```bash
# Single file
any2md report.pdf

# Multiple files
any2md report.pdf proposal.docx "meeting notes.pdf"

# HTML file
any2md page.html

# Web page by URL
any2md https://example.com/article

# Mixed batch — PDFs, DOCX, HTML, and URLs together
any2md doc.pdf page.html https://example.com
```

### Directory scanning

```bash
# Scan a specific directory
any2md --input-dir ./documents

# Convert everything in the current directory (default behavior)
any2md
```

### Options

```bash
# Custom output directory
any2md -o ./converted report.pdf

# Overwrite existing files
any2md --force

# Strip hyperlinks from output
any2md --strip-links doc.pdf

# Combine options
any2md -f -o ./out --strip-links docs/*.pdf docs/*.docx
```

### Alternative invocations

```bash
# Module mode (works without installing via pip)
python -m any2md report.pdf

# Legacy script (backward compatibility)
python3 mdconv.py report.pdf
```

## Output Format

Every converted file has YAML frontmatter followed by cleaned Markdown. The frontmatter fields vary by source format:

**PDF** — includes page count:

```markdown
---
title: "Quarterly Financial Report"
source_file: "Q3 Report 2024.pdf"
pages: 12
type: pdf
---
```

**DOCX** — includes word count:

```markdown
---
title: "Project Proposal"
source_file: "proposal.docx"
word_count: 3847
type: docx
---
```

**HTML file** — includes word count:

```markdown
---
title: "Page Title"
source_file: "page.html"
word_count: 1234
type: html
---
```

**URL** — records source URL instead of filename:

```markdown
---
title: "Article Title"
source_url: "https://example.com/article"
word_count: 567
type: html
---
```

## CLI Reference

```
usage: any2md [-h] [--input-dir PATH] [--force] [--output-dir PATH] [--strip-links] [files ...]

Convert PDF, DOCX, and HTML files to LLM-optimized Markdown.

positional arguments:
  files                 Files or URLs to convert. Supports PDF, DOCX, HTML
                        files and http(s) URLs. If omitted, converts all
                        supported files in the current directory.

options:
  -h, --help            show this help message and exit
  --input-dir, -i PATH  Directory to scan for supported files (PDF, DOCX, HTML)
  --force, -f           Overwrite existing .md files
  --output-dir, -o PATH Output directory (default: ./Text)
  --strip-links         Remove markdown links, keeping only the link text
```

## Architecture

```
User Input (files, URLs, flags)
         │
         ▼
      cli.py ─── parse args, classify URLs vs file paths
         │
         ▼
converters/__init__.py ─── dispatch by extension
         │
    ┌────┼────┐
    ▼    ▼    ▼
 pdf  docx  html ─── format-specific extraction
    │    │    │
    └────┼────┘
         ▼
      utils.py ─── clean, title-extract, sanitize, frontmatter
         │
         ▼
      Output ─── YAML frontmatter + Markdown → output_dir/
```

### Extraction pipelines

| Format | Pipeline |
|--------|----------|
| **PDF** | `pymupdf4llm.to_markdown()` → clean → frontmatter |
| **DOCX** | `mammoth` (DOCX → HTML) → `markdownify` (HTML → Markdown) → clean → frontmatter |
| **HTML/URL** | BS4 pre-clean → `trafilatura` extract (fallback: `markdownify`) → clean → frontmatter |

### Adding a new format

1. Create `any2md/converters/newformat.py` with a `convert_newformat(path, output_dir, force, strip_links_flag) → bool` function
2. Add the extension and function to `CONVERTERS` in `any2md/converters/__init__.py`
3. Add the extension to `SUPPORTED_EXTENSIONS`

## License

MIT
