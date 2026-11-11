"""Raise a Python warning as if from another library's source file."""

from __future__ import annotations

import types
import warnings

# A fixed statement. Compiled under a chosen file name and run with a
# chosen ``__name__``, it gives a real frame for that file and module,
# the way a warning from Docling or torch arrives, without either library.
_SOURCE = "warnings.warn(message, category)\n"


def warn_from(
    filename: str, module: str, message: str, category: type[Warning] = UserWarning
) -> None:
    """Raise ``message`` from code in ``filename`` whose module is ``module``."""
    code = compile(_SOURCE, filename, "exec")
    namespace = {
        "__name__": module,
        "warnings": warnings,
        "message": message,
        "category": category,
    }
    types.FunctionType(code, namespace)()
