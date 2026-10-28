from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from benchmarks import leakage_benchmark, tune_leakage
from leakage import config
from leakage.evaluate import list_variants, summarize, wilson


def test_tuning_script_is_dev_only() -> None:
    assert tune_leakage.PARTITION == "dev"
    src = inspect.getsource(tune_leakage)
    assert '"eval"' not in src.replace("`eval`", "").replace("eval partition", "")


def test_list_variants_partitions(tmp_path: Path) -> None:
    from benchmarks.planted_bugs.generate import write_variants

    write_variants(tmp_path)
    assert len(list_variants("dev", tmp_path)) == 24 and len(list_variants("eval", tmp_path)) == 24


def test_wilson_interval() -> None:
    lo, hi = wilson(3, 3)
    assert 0.4 < lo < 1.0 and hi == pytest.approx(1.0)
    assert wilson(0, 0) == (0.0, 1.0)


def test_summarize_counts() -> None:
    rows = [
        {
            "bug_type": "a",
            "hit": True,
            "column_hit": True,
            "twin_false_alarm": False,
            "variant_id": "a0",
            "twin_findings": [],
        },
        {
            "bug_type": "a",
            "hit": False,
            "column_hit": None,
            "twin_false_alarm": True,
            "variant_id": "a1",
            "twin_findings": ["x:y"],
        },
    ]
    s = summarize(rows)
    assert s["by_bug_type"]["a"]["recall"] == 0.5 and s["twin_fpr"] == 0.5
    assert s["twin_false_alarm_examples"][0]["variant_id"] == "a1"


def test_assert_frozen_requires_matching_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen = tmp_path / "frozen.sha256"
    monkeypatch.setattr(config, "FROZEN_HASH_PATH", frozen)
    with pytest.raises(RuntimeError, match="not frozen"):
        config.assert_frozen()
    frozen.write_text("0" * 64)
    with pytest.raises(RuntimeError, match="changed after freeze"):
        config.assert_frozen()
    frozen.write_text(config.thresholds_hash())
    assert config.assert_frozen() == config.thresholds_hash()


def test_leakage_benchmark_refuses_unfrozen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(leakage_benchmark, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(config, "FROZEN_HASH_PATH", tmp_path / "missing")
    with pytest.raises(RuntimeError, match="not frozen"):
        leakage_benchmark.run_leakage_benchmark()


def test_leakage_benchmark_refuses_second_eval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "leakage_v0.json").write_text("{}")
    monkeypatch.setattr(leakage_benchmark, "RESULTS_DIR", tmp_path)
    assert leakage_benchmark.run_leakage_benchmark() == 2
