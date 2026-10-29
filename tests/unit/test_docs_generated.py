"""Generated docs stay in sync with their sources."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_adr_index_is_current() -> None:
    p = subprocess.run(
        [sys.executable, "scripts/gen_adr_index.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, p.stdout


def test_every_adr_file_is_indexed() -> None:
    index = (ROOT / "docs" / "adr" / "README.md").read_text(encoding="utf-8")
    for f in (ROOT / "docs" / "adr").glob("[0-9][0-9][0-9]-*.md"):
        assert f.name in index


def test_changelog_renders_sections_from_tags() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import gen_changelog

    text = gen_changelog.render(
        [("v8", "2025-12-31", []), ("v9", "2026-01-01", ["feat: a", "fix: b"])]
    )
    assert (
        text.index("## v9") < text.index("## v8") and "- feat: a" in text and "(merge only)" in text
    )
