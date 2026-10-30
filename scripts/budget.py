"""Shared, file-locked budget ledger for parallel workstreams (run 9).

    uv run python scripts/budget.py reserve groq 5      # prints ok / deny, exit 0 / 1
    uv run python scripts/budget.py commit groq 4       # actual usage (releases the rest)
    uv run python scripts/budget.py status

Kinds: groq, gemini (per UTC day, cap 120 each), ci_runs / ci_minutes / e2b / hf_build (per run).
The ledger lives in the MAIN checkout's `.budget/ledger.json` (gitignored), found through
`git rev-parse --git-common-dir`, so every worktree shares one file. Override with BUDGET_LEDGER.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DAILY = {"groq": 120, "gemini": 120}
RUN = {"ci_runs": 20, "ci_minutes": 250, "e2b": 60, "hf_build": 6}


def _path() -> Path:
    if os.environ.get("BUDGET_LEDGER"):
        return Path(os.environ["BUDGET_LEDGER"])
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    return Path(common).parent / ".budget" / "ledger.json"


class _Lock:
    def __init__(self, p: Path) -> None:
        self.p = p.with_suffix(".lock")

    def __enter__(self) -> None:
        for _ in range(600):
            try:
                self.fd = os.open(self.p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return
            except FileExistsError:
                try:
                    if time.time() - self.p.stat().st_mtime > 30:  # stale lock
                        self.p.unlink()
                except OSError:
                    pass
                time.sleep(0.1)
        raise TimeoutError("budget ledger lock")

    def __exit__(self, *a: object) -> None:
        os.close(self.fd)
        self.p.unlink(missing_ok=True)


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _load(p: Path) -> dict[str, Any]:
    if p.exists():
        d: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
        return d
    return {"daily": {}, "run": {}}


def _used(d: dict[str, Any], kind: str) -> int:
    if kind in DAILY:
        return int(d["daily"].get(_today(), {}).get(kind, 0))
    return int(d["run"].get(kind, 0))


def _cap(kind: str) -> int:
    if kind not in DAILY and kind not in RUN:
        raise SystemExit(f"unknown kind {kind}; known: {sorted({**DAILY, **RUN})}")
    return DAILY.get(kind) or RUN[kind]


def _add(d: dict[str, Any], kind: str, n: int) -> None:
    if kind in DAILY:
        day = d["daily"].setdefault(_today(), {})
        day[kind] = max(0, int(day.get(kind, 0)) + n)
    else:
        d["run"][kind] = max(0, int(d["run"].get(kind, 0)) + n)


def reserve(kind: str, n: int, path: Path | None = None) -> bool:
    p = path or _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with _Lock(p):
        d = _load(p)
        if _used(d, kind) + n > _cap(kind):
            return False
        _add(d, kind, n)
        p.write_text(json.dumps(d, indent=1, sort_keys=True), encoding="utf-8")
        return True


def commit(kind: str, actual: int, reserved: int | None = None, path: Path | None = None) -> None:
    """Record real usage; if `reserved` is given the unused part is released."""
    p = path or _path()
    with _Lock(p):
        d = _load(p)
        if reserved is not None:
            _add(d, kind, actual - reserved)
        p.write_text(json.dumps(d, indent=1, sort_keys=True), encoding="utf-8")


def status(path: Path | None = None) -> dict[str, Any]:
    p = path or _path()
    d = _load(p)
    return {k: f"{_used(d, k)}/{_cap(k)}" for k in [*DAILY, *RUN]} | {"utc_day": _today()}


def main(argv: list[str] | None = None) -> int:
    a = sys.argv[1:] if argv is None else argv
    if not a or a[0] == "status":
        print(json.dumps(status()))
        return 0
    cmd, kind, n = a[0], a[1], int(a[2])
    if cmd == "reserve":
        ok = reserve(kind, n)
        print("ok" if ok else "deny")
        return 0 if ok else 1
    if cmd == "commit":
        commit(kind, n, int(a[3]) if len(a) > 3 else None)
        print("committed")
        return 0
    raise SystemExit("usage: budget.py reserve|commit|status <kind> <n> [reserved]")


if __name__ == "__main__":
    sys.exit(main())
