from __future__ import annotations

from pathlib import Path

from scripts.secret_scan import scan_paths, scan_text


def _fake_aws() -> str:
    return "AKIA" + "ABCDEFGHIJKLMNOP"  # built at runtime: nothing secret-shaped is committed


def test_detects_fake_secret() -> None:
    assert scan_text(f"key = '{_fake_aws()}'")[0][0] == "aws-access-key"


def test_detects_generic_assignment() -> None:
    assert scan_text('api_key = "' + "x" * 32 + '"')


def test_clean_text_passes() -> None:
    assert scan_text("GROQ_API_KEY=\nprint('hello')") == []


def test_scan_paths_flags_file(tmp_path: Path) -> None:
    f = tmp_path / "leak.py"
    f.write_text(f"X = '{_fake_aws()}'\n", encoding="utf-8")
    assert scan_paths([f])
