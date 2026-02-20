# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- HTML file conversion (.html, .htm) with BeautifulSoup pre-cleaning, trafilatura content extraction, and markdownify fallback
- URL fetching — convert web pages directly by passing a URL as a positional argument
- `--strip-links` flag to remove markdown hyperlinks from output, keeping only link text
- .html/.htm support in `--input-dir` batch scanning
- Package architecture (`any2md/` package with `converters` subpackage)
- `python -m any2md` entry point
- Shared utilities module (`any2md/utils.py`) with `strip_links()` and `url_to_filename()`
- YAML frontmatter for HTML outputs includes `source_url` when converted from a URL

### Changed
- Refactored from single-file (`any2md.py`) to package architecture
- `any2md.py` is now a thin wrapper for backward compatibility
- Updated `SUPPORTED_EXTENSIONS` to include `.html` and `.htm`

### Dependencies
- Added `trafilatura` for HTML content extraction and URL fetching
- Added `beautifulsoup4` for HTML pre-cleaning
