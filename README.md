# pdf-to-markdown

Convert PDF and DOCX files to clean, LLM-optimized Markdown with YAML frontmatter.

Built on [PyMuPDF](https://pymupdf.readthedocs.io/) and [pymupdf4llm](https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/) for PDF extraction, and [mammoth](https://github.com/mwilliamson/python-mammoth) + [markdownify](https://github.com/matthewwithanm/python-markdownify) for DOCX conversion. Preserves document structure — headings, lists, tables, and formatting — while stripping out noise like images and excessive whitespace.

## Features

- **Multi-format support** — Converts both PDF and DOCX files to Markdown
- **LLM-ready output** — Clean markdown optimized for ingestion by language models
- **YAML frontmatter** — Each file includes title, source filename, and format-specific metadata (page count for PDFs, word count for DOCX)
- **Batch processing** — Convert a single file or every supported file in a directory
- **Auto-detection** — Routes to the correct converter based on file extension
- **Smart skip** — Won't overwrite existing conversions unless `--force` is used
- **Filename sanitization** — Handles spaces, special characters, and unicode dashes
- **Title extraction** — Automatically pulls the document title from the first heading

## Installation

Requires Python 3.8+.

```bash
pip install pymupdf pymupdf4llm mammoth markdownify
```

Or using the requirements file:

```bash
pip install -r requirements.txt
```

Clone the repository:

```bash
git clone https://github.com/rocklambros/pdf-to-markdown.git
cd pdf-to-markdown
```

## Usage

### Convert all supported files in the script directory

```bash
python3 pdf2md.py
```

### Convert specific files

```bash
python3 pdf2md.py report.pdf proposal.docx "meeting notes.pdf"
```

### Scan a directory for supported files

```bash
python3 pdf2md.py --input-dir ./documents
```

### Overwrite existing markdown files

```bash
python3 pdf2md.py --force
```

### Custom output directory

```bash
python3 pdf2md.py --output-dir ./converted
```

### Combine options

```bash
python3 pdf2md.py -f -o ./out docs/*.pdf docs/*.docx
```

By default, converted files are written to a `Text/` subdirectory next to the script.

## Output Format

Each converted file includes YAML frontmatter followed by the cleaned markdown content.

**PDF output:**

```markdown
---
title: "Quarterly Financial Report"
source_file: "Q3 Report 2024.pdf"
pages: 12
type: pdf
---

# Quarterly Financial Report

Document content here...
```

**DOCX output:**

```markdown
---
title: "Project Proposal"
source_file: "proposal.docx"
word_count: 3847
type: docx
---

# Project Proposal

Document content here...
```

## CLI Reference

```
usage: pdf2md.py [-h] [--input-dir PATH] [--force] [--output-dir PATH] [files ...]

Convert PDF and DOCX files to LLM-optimized Markdown.

positional arguments:
  files                 PDF or DOCX files to convert (default: all supported files in script dir)

options:
  -h, --help            show this help message and exit
  --input-dir, -i PATH  Directory to scan for supported files (PDF, DOCX)
  --force, -f           Overwrite existing .md files
  --output-dir, -o PATH Output directory (default: ./Text)
```

## How It Works

1. **Discovery** — Finds PDF and DOCX files from command-line args or scans the script directory
2. **Routing** — Dispatches each file to the appropriate converter based on extension
3. **Extraction** — PDFs use `pymupdf4llm.to_markdown()`; DOCX files use `mammoth` (DOCX→HTML) then `markdownify` (HTML→Markdown)
4. **Title detection** — Searches for the first H1-H3 heading; falls back to the filename
5. **Cleanup** — Collapses excessive blank lines and strips trailing whitespace
6. **Frontmatter** — Prepends YAML metadata (page count for PDFs, word count for DOCX)
7. **Write** — Saves to the output directory with a sanitized filename

## License

MIT
