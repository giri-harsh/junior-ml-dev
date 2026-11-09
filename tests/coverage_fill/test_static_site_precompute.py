"""`precompute_runs` end to end through the real DemoService, queue and database, with only the
child-process executor replaced by a fake that writes the files the real child would."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.api.demo import service as service_mod
from apps.api.demo.service import DemoJob, ExecOutcome
from apps.space.static_site import RunRecord, build_site, load_runs, precompute_runs
from tests.demo.helpers import make_samples

STEPS = [
    {"idx": 0, "tool": "profile_dataset", "server": "data-tools", "ok": True, "latency_s": 0.1},
    {"idx": 1, "tool": "train_model", "server": "experiments", "ok": True, "latency_s": 0.2},
]


class ChildLike:
    """Writes job.json, trace.json and report.html where the real subprocess executor would."""

    def __init__(self, status: str = "done", fail_for: str | None = None) -> None:
        self.status, self.fail_for = status, fail_for
        self.seen: list[str] = []

    def __call__(self, job: DemoJob) -> ExecOutcome:
        job.run_dir.mkdir(parents=True, exist_ok=True)
        (job.run_dir / "job.json").write_text(
            json.dumps({"config": job.config.model_dump(mode="json")}), encoding="utf-8"
        )
        self.seen.append(job.config.task.name)
        if self.fail_for == job.config.task.name:
            return ExecOutcome("failed", error="boom")
        out = job.run_dir / "out" / job.run_id
        out.mkdir(parents=True, exist_ok=True)
        (out / "trace.json").write_text(json.dumps({"steps": STEPS}), encoding="utf-8")
        report = out / "report.html"
        report.write_text(f"<html>report for {job.config.task.name}</html>", encoding="utf-8")
        result = {
            "status": "done", "chosen_family": "linear", "val_score": 0.81, "review": "APPROVE",
            "n_steps": 2, "latency_s": 1.5, "dropped": [], "unresolved": [],
            "report": {"html": str(report)},
        }  # fmt: skip
        return ExecOutcome(self.status, result)


def test_precompute_records_each_sample_and_caches_report_and_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = ChildLike()
    monkeypatch.setattr(service_mod, "subprocess_executor", child)
    samples = make_samples(tmp_path)
    cache = tmp_path / "cache"

    runs = precompute_runs(samples, cache)

    assert [r.key for r in runs] == ["diabetes", "credit-g", "wine-quality"]
    assert child.seen == ["diabetes", "credit-g", "wine-quality"]
    first = runs[0]
    assert first.status == "done" and first.run_id.startswith("demo-")
    assert (first.rows, first.cols) == (300, 3)
    assert first.openml_id == 37 and first.task_type == "binary" and first.metric == "roc_auc"
    assert first.summary["chosen_family"] == "linear" and first.summary["val_score"] == 0.81
    assert first.steps == STEPS
    assert first.wall_s >= 0.0
    assert first.budget["max_wall_s"] == 55.0 and first.budget["flaml_budget_s"] == 15.0
    assert first.ran_at.endswith(" UTC")
    assert (cache / "credit-g" / "report.html").read_text(encoding="utf-8") == (
        "<html>report for credit-g</html>"
    )
    # the on-disk index round-trips to the same records and feeds the site builder
    loaded = load_runs(cache)
    assert loaded == runs and all(isinstance(r, RunRecord) for r in loaded)
    written = build_site(tmp_path / "site", cache, "# Verified metrics\n\n## H\n\n- x\n")
    assert "runs/wine-quality/index.html" in written


def test_precompute_can_be_limited_to_some_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = ChildLike()
    monkeypatch.setattr(service_mod, "subprocess_executor", child)
    runs = precompute_runs(make_samples(tmp_path), tmp_path / "cache", keys=["wine-quality"])
    assert [r.key for r in runs] == ["wine-quality"] == child.seen
    assert [r.key for r in load_runs(tmp_path / "cache")] == ["wine-quality"]
    assert not (tmp_path / "cache" / "diabetes").exists()


def test_precompute_skips_samples_that_are_not_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = ChildLike()
    monkeypatch.setattr(service_mod, "subprocess_executor", child)
    samples = make_samples(tmp_path)
    (samples / "credit-g.csv").unlink()  # manifest entry stays, the file is gone
    runs = precompute_runs(samples, tmp_path / "cache")
    assert [r.key for r in runs] == ["diabetes", "wine-quality"]


def test_precompute_refuses_a_run_that_did_not_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service_mod, "subprocess_executor", ChildLike(fail_for="credit-g"))
    with pytest.raises(RuntimeError, match=r"credit-g: run did not finish \(failed\)"):
        precompute_runs(make_samples(tmp_path), tmp_path / "cache")
    assert not (tmp_path / "cache" / "runs.json").exists()  # nothing half-published
