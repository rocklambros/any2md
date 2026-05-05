"""Process-lifetime cache of DocumentConverter instances.

Stability: experimental for v1.1.0. Public API surface:
- `release_models()` — imperative escape hatch
- `docling_session()` — contextmanager (preferred)
- `ANY2MD_DOCLING_CACHE=0` — disable cache entirely

Other names in this module are internal and may change.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator

_MAX_RESIDENT = 2  # Empirically: pdf + docx are the only construction
                   # sites; 2 slots covers 99% of mixed batches with
                   # bounded RSS (~1GB extra steady-state worst case).

_CACHE_DISABLED_ENV = "ANY2MD_DOCLING_CACHE"
