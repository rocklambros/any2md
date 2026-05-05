"""any2md — convert documents to LLM-friendly Markdown."""

from any2md._docling_cache import docling_session, release_models

__version__ = "1.1.0"

__all__ = [
    "__version__",
    "docling_session",
    "release_models",
]
