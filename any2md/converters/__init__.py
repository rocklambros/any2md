"""Converter dispatcher for any2md."""

import sys
from pathlib import Path

from any2md.converters.pdf import convert_pdf
from any2md.converters.docx import convert_docx
from any2md.converters.html import convert_html

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm"}

CONVERTERS = {
    ".pdf": convert_pdf,
    ".docx": convert_docx,
    ".html": convert_html,
    ".htm": convert_html,
}


def convert_file(
    file_path: Path,
    output_dir: Path,
    force: bool = False,
    strip_links_flag: bool = False,
) -> bool:
    """Dispatch to the appropriate converter based on file extension."""
    ext = file_path.suffix.lower()
    converter = CONVERTERS.get(ext)
    if converter is None:
        print(f"  UNSUPPORTED: {file_path.name} (no converter for {ext})", file=sys.stderr)
        return False
    return converter(file_path, output_dir, force=force, strip_links_flag=strip_links_flag)
