"""Every number shown anywhere must come from a file written by this module.

Each result file is stamped with the command, git SHA, date and an honest conditions block.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RESULTS_DIR = Path(__file__).resolve().parent / "results"


class Conditions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm: Literal["real", "mocked", "recorded", "none"]
    sandbox: Literal["e2b", "local", "fake", "none"]
    n: int = Field(ge=0, description="sample size the numbers are computed over")
    machine_id: str = Field(default_factory=lambda: platform.node() or "unknown")
    notes: str = ""


class ResultFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    command: str
    git_sha: str
    date: str
    conditions: Conditions
    results: dict[str, Any]


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def write_result(
    name: str,
    results: dict[str, Any],
    conditions: Conditions,
    *,
    command: str | None = None,
    out_dir: Path | None = None,
) -> Path:
    """Write `<out_dir>/<name>.json`; returns the path. Refuses path-like names."""
    if "/" in name or "\\" in name or not name:
        raise ValueError(f"invalid result name: {name!r}")
    record = ResultFile(
        name=name,
        command=command or " ".join(sys.argv),
        git_sha=_git_sha(),
        date=datetime.now(UTC).isoformat(timespec="seconds"),
        conditions=conditions,
        results=results,
    )
    target_dir = out_dir or RESULTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{name}.json"
    path.write_text(
        json.dumps(record.model_dump(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def load_result(path: Path) -> ResultFile:
    return ResultFile.model_validate_json(path.read_text(encoding="utf-8"))
