"""Load ONLY an allowlist of variables from .env files into os.environ (never logged or copied).

The repo .env may contain unrelated credentials; everything outside ALLOWED is ignored.
"""

from __future__ import annotations

import os
from pathlib import Path

ALLOWED = ("GEMINI_API_KEY", "GROQ_API_KEY", "E2B_API_KEY")
DEFAULT_FILES = (Path(".env"), Path(r"C:\Work\Projects\Prod_rag\prod_rag\.env"))


def load_llm_keys(
    files: tuple[Path, ...] = DEFAULT_FILES, allowed: tuple[str, ...] = ALLOWED
) -> list[str]:
    """Return the NAMES that are present after loading (values are never returned)."""
    for f in files:
        if not f.is_file():
            continue
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            name, value = name.strip(), value.strip().strip('"').strip("'")
            if name in allowed and value and not os.environ.get(name):
                os.environ[name] = value
    return [n for n in allowed if os.environ.get(n)]
