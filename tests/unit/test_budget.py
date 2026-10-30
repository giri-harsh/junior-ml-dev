from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import budget  # noqa: E402


def test_reserve_denies_over_cap_and_commit_releases_the_unused_part(tmp_path: Path) -> None:
    p = tmp_path / "l.json"
    assert budget.reserve("e2b", 50, p) and budget.reserve("e2b", 10, p)
    assert not budget.reserve("e2b", 1, p)  # 60 cap reached
    budget.commit("e2b", actual=2, reserved=10, path=p)
    assert budget.reserve("e2b", 8, p) and not budget.reserve("e2b", 1, p)


def test_daily_kinds_are_per_utc_day_and_status_reports_usage(tmp_path: Path) -> None:
    p = tmp_path / "l.json"
    assert budget.reserve("groq", 120, p) and not budget.reserve("groq", 1, p)
    assert budget.status(p)["groq"] == "120/120" and budget.status(p)["gemini"] == "0/120"
