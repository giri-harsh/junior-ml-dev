from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from mcp_servers.data_tools import service
from mcp_servers.data_tools.service import (
    GuardError,
    LeakageRequest,
    ProfileRequest,
    StoryRequest,
)


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    r = tmp_path / "data"
    r.mkdir()
    monkeypatch.setenv("DATA_TOOLS_ROOTS", str(r))
    monkeypatch.setenv("TRAJECTORY_DIR", str(tmp_path / "traj"))
    from trajectory import emit

    emit.configure(tmp_path / "traj")
    return r


def _csv(root: Path, n: int = 300, name: str = "d.csv") -> Path:
    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "x": rng.normal(size=n),
            "seg": rng.choice(["a", "b"], n),
            "leak": 0,
            "target": rng.integers(0, 2, n),
        }
    )
    df["leak"] = df["target"]
    p = root / name
    df.to_csv(p, index=False)
    return p


def test_profile_dataset(root: Path) -> None:
    res = service.profile_dataset(
        ProfileRequest(path=str(_csv(root)), target="target", run_id="t1")
    )
    assert res.run_id == "t1" and res.profile.n_rows == 300
    assert res.profile.target is not None and res.profile.target.task_type == "binary"
    assert {c.name for c in res.profile.columns} == {"x", "seg", "leak", "target"}


def test_detect_leakage_finds_planted_proxy(root: Path) -> None:
    res = service.detect_leakage(LeakageRequest(path=str(_csv(root)), target="target"))
    assert any(f.columns == ["leak"] and f.severity.value == "high" for f in res.findings)
    assert len(res.thresholds_sha256) == 64


def test_data_story_markdown(root: Path) -> None:
    res = service.data_story(StoryRequest(path=str(_csv(root)), target="target"))
    assert res.markdown.startswith("# Data Story") and "`leak`" in res.markdown


def test_events_are_emitted_with_run_id(root: Path, tmp_path: Path) -> None:
    service.profile_dataset(ProfileRequest(path=str(_csv(root)), run_id="trace1"))
    assert (tmp_path / "traj" / "trace1.jsonl").exists()


def test_path_traversal_and_outside_root_rejected(root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "secret.csv"
    outside.write_text("a\n1\n")
    for bad in (str(outside), str(root / ".." / "secret.csv"), "does/not/exist.csv", "a\0b.csv"):
        with pytest.raises(GuardError):
            service.resolve_path(bad)


def test_scorer_data_always_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hidden = tmp_path / "scorer_data" / "task"
    hidden.mkdir(parents=True)
    f = hidden / "test_labels.csv"
    f.write_text("a\n1\n")
    monkeypatch.setenv("DATA_TOOLS_ROOTS", str(tmp_path))  # even when the parent is allowed
    with pytest.raises(GuardError, match="not accessible"):
        service.resolve_path(str(f))


def test_extension_allowlist(root: Path) -> None:
    f = root / "x.pkl"
    f.write_bytes(b"x")
    with pytest.raises(GuardError, match="unsupported"):
        service.resolve_path(str(f))


def test_oversized_file_rejected(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _csv(root)
    monkeypatch.setattr(service, "MAX_FILE_BYTES", 100)
    with pytest.raises(GuardError, match="cap"):
        service.profile_dataset(ProfileRequest(path=str(p)))


def test_row_cap_uses_seeded_sampling(root: Path) -> None:
    p = _csv(root, n=1000)
    a = service.profile_dataset(ProfileRequest(path=str(p), max_rows=200, seed=3))
    b = service.profile_dataset(ProfileRequest(path=str(p), max_rows=200, seed=3))
    assert a.profile.sample is not None and a.profile.sample.sampled
    assert a.profile.sample.n_used == 200 and a.profile.sample.n_full == 1000
    assert a.profile.model_dump() == b.profile.model_dump()


def test_unknown_target_rejected(root: Path) -> None:
    with pytest.raises(GuardError, match="not in columns"):
        service.detect_leakage(LeakageRequest(path=str(_csv(root)), target="nope"))


def test_timeout_is_reported(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter(range(10_000))  # fake clock: advances 1s per call, so any budget < 1s expires
    monkeypatch.setattr("leakage.models.time.monotonic", lambda: float(next(ticks)))
    with pytest.raises(GuardError, match="time budget"):
        service.detect_leakage(
            LeakageRequest(path=str(_csv(root)), target="target", time_budget_s=1e-9)
        )


@pytest.mark.parametrize(
    "bad",
    [
        {"path": ""},
        {"path": "a.csv", "max_rows": 5},
        {"path": "a.csv", "max_rows": 10**9},
        {"path": "a.csv", "run_id": "../evil"},
        {"path": "a.csv", "extra_field": 1},
        {"path": "a.csv", "seed": -1},
    ],
)
def test_schema_validation_failures(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ProfileRequest(**bad)  # type: ignore[arg-type]


def test_leakage_request_requires_target_and_bounds_budget() -> None:
    with pytest.raises(ValidationError):
        LeakageRequest(path="a.csv")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        LeakageRequest(path="a.csv", target="t", time_budget_s=10_000)
