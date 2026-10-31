"""Demo-mode settings. Hard ceilings are constants: an env var may lower them, never raise them."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_URL = "https://github.com/giri-harsh/junior-ml-dev"

# Ceilings (the task contract). Env overrides are clamped to these.
MAX_WALL_S = 90.0  # hard wall clock for one run, process start to finish
MAX_FLAML_S = 20.0  # FLAML AutoML budget inside one run
SOFT_WALL_S = 55.0  # the agent stops searching at this point and wraps up (report, review)

# Tools the demo agent may never call, whatever a planner proposes.
BLOCKED_TOOLS = frozenset(
    {"engineer_features", "check_code_policy", "package_model", "deploy_local"}
)


def demo_enabled() -> bool:
    """DEMO_MODE=1 turns the demo guard on. Anything else is a strict no-op."""
    return os.environ.get("DEMO_MODE", "") == "1"


def _f(name: str, default: float, ceiling: float | None = None) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        value = default
    return min(value, ceiling) if ceiling is not None else value


def _i(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class DemoSettings:
    data_dir: Path  # sample CSVs + manifest.json (part of the image)
    state_dir: Path  # SQLite files and per-run directories (ephemeral)
    site_dir: Path  # rendered landing page
    max_wall_s: float
    soft_wall_s: float
    flaml_s: float
    queue_max: int  # runs waiting behind the one that is executing
    history_cap: int  # finished runs kept (and their files)
    history_ttl_s: float
    ip_runs_per_window: int
    ip_window_s: float
    global_runs_per_hour: int
    read_per_min: int  # per-IP cap on every other /demo/api call
    proxy_hops: int  # trusted reverse proxies in front (X-Forwarded-For parsing)

    @classmethod
    def from_env(cls) -> DemoSettings:
        wall = _f("DEMO_MAX_WALL_S", MAX_WALL_S, MAX_WALL_S)
        return cls(
            data_dir=Path(os.environ.get("DEMO_DATA_DIR", "data/demo/samples")),
            state_dir=Path(os.environ.get("DEMO_STATE_DIR", "data/demo/state")),
            site_dir=Path(os.environ.get("DEMO_SITE_DIR", "data/demo/site")),
            max_wall_s=wall,
            soft_wall_s=min(_f("DEMO_SOFT_WALL_S", SOFT_WALL_S, SOFT_WALL_S), wall),
            flaml_s=_f("DEMO_FLAML_S", 15.0, MAX_FLAML_S),
            queue_max=_i("DEMO_QUEUE_MAX", 3),
            history_cap=_i("DEMO_HISTORY_CAP", 20),
            history_ttl_s=_f("DEMO_HISTORY_TTL_S", 6 * 3600.0),
            ip_runs_per_window=_i("DEMO_IP_RUNS", 4),
            ip_window_s=_f("DEMO_IP_WINDOW_S", 600.0),
            global_runs_per_hour=_i("DEMO_GLOBAL_RUNS_PER_HOUR", 40),
            read_per_min=_i("DEMO_READ_PER_MIN", 240),
            proxy_hops=max(0, int(_f("DEMO_PROXY_HOPS", 0))),
        )
