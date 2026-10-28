"""Eval-once ledger: each frozen thresholds hash gets exactly one evaluation.

`claim()` writes the entry BEFORE the evaluation runs, so a crash mid-run cannot grant a second
look. Infra crashes are re-run piecewise via `mark_infra_retry()`, which is logged, never silent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LEDGER_PATH = Path("benchmarks/eval_ledger.json")


class EvalAlreadySpent(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def is_spent(thresholds_hash: str, path: Path | None = None) -> bool:
    path = path or LEDGER_PATH
    return thresholds_hash in _load(path)


def claim(
    thresholds_hash: str, result_file: str, partitions: list[str], path: Path | None = None
) -> None:
    path = path or LEDGER_PATH
    ledger = _load(path)
    if thresholds_hash in ledger:
        raise EvalAlreadySpent(
            f"thresholds {thresholds_hash[:12]} already evaluated: "
            f"{ledger[thresholds_hash]['result_file']}"
        )
    ledger[thresholds_hash] = {
        "result_file": result_file,
        "partitions": partitions,
        "status": "claimed",
        "infra_retries": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def mark(thresholds_hash: str, status: str, path: Path | None = None) -> None:
    path = path or LEDGER_PATH
    ledger = _load(path)
    ledger[thresholds_hash]["status"] = status
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def mark_infra_retry(thresholds_hash: str, reason: str, path: Path | None = None) -> None:
    path = path or LEDGER_PATH
    ledger = _load(path)
    ledger[thresholds_hash]["infra_retries"].append(reason)
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
