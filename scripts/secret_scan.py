"""Regex secret scanner: pre-commit fallback when gitleaks is not installed.

Usage: python scripts/secret_scan.py [--staged | paths...]. Exit 1 on any finding.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS: dict[str, re.Pattern[str]] = {
    "aws-access-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github-token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "groq-key": re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b"),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "e2b-key": re.compile(r"\be2b_[a-f0-9]{30,}\b"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "generic-secret-assign": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"][A-Za-z0-9/+_\-]{24,}['\"]"
    ),
}
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache"}
SKIP_FILES = {"uv.lock"}


def scan_text(text: str) -> list[tuple[str, int]]:
    findings: list[tuple[str, int]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, pattern in PATTERNS.items():
            if pattern.search(line):
                findings.append((name, lineno))
    return findings


def scan_paths(paths: list[Path]) -> list[tuple[Path, str, int]]:
    out: list[tuple[Path, str, int]] = []
    for path in paths:
        if path.name in SKIP_FILES or SKIP_DIRS & set(path.parts) or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        out.extend((path, name, line) for name, line in scan_text(text))
    return out


def _staged() -> list[Path]:
    res = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [Path(p) for p in res.stdout.splitlines() if p]


def _all_tracked_or_new() -> list[Path]:
    res = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [Path(p) for p in res.stdout.splitlines() if p]


def main(argv: list[str]) -> int:
    if argv == ["--staged"]:
        paths = _staged()
    elif argv:
        paths = [Path(a) for a in argv]
    else:
        paths = _all_tracked_or_new()
    findings = scan_paths(paths)
    for path, name, line in findings:
        print(f"SECRET? {path}:{line} [{name}]", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
