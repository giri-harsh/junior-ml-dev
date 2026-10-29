from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from benchmarks import leakage_benchmark, tune_leakage
from leakage import config, ledger
from leakage.evaluate import list_variants, summarize, wilson


def test_tuning_script_is_dev_only() -> None:
    assert tune_leakage.PARTITION == "dev"
    src = inspect.getsource(tune_leakage)
    assert '"eval"' not in src.replace("`eval`", "").replace("eval partition", "")


def test_list_variants_partitions(tmp_path: Path) -> None:
    from benchmarks.planted_bugs.generate import write_variants

    write_variants(tmp_path)
    assert all(len(list_variants(p, tmp_path)) == 24 for p in ("eval_v0", "eval2", "eval3"))


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
    frozen = tmp_path / "frozen"
    frozen.write_text(config.thresholds_hash())
    monkeypatch.setattr(config, "FROZEN_HASH_PATH", frozen)
    monkeypatch.setattr(leakage_benchmark, "RESULTS_DIR", tmp_path)
    ledger_path = tmp_path / "ledger.json"
    monkeypatch.setattr(ledger, "LEDGER_PATH", ledger_path)
    ledger_path.write_text(json.dumps({config.thresholds_hash(): {"status": "spent"}}))
    assert leakage_benchmark.run_leakage_benchmark() == 2


def test_ledger_claim_is_one_shot(tmp_path: Path) -> None:
    path = tmp_path / "l.json"
    ledger.claim("abc", "r.json", ["eval2"], path)
    assert ledger.is_spent("abc", path)
    with pytest.raises(ledger.EvalAlreadySpent):
        ledger.claim("abc", "r.json", ["eval2"], path)
    ledger.mark_infra_retry("abc", "disk full", path)
    assert json.loads(path.read_text())["abc"]["infra_retries"] == ["disk full"]


def test_v0_hash_is_recorded_as_spent() -> None:
    led = json.loads(Path("benchmarks/eval_ledger.json").read_text())
    assert any(v["status"] == "spent" and "leakage_v0" in v["result_file"] for v in led.values())


def test_ledger_default_path_resolves_at_call_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression: a default bound at import time once let a test spend the real ledger slot."""
    target = tmp_path / "late.json"
    monkeypatch.setattr(ledger, "LEDGER_PATH", target)
    ledger.claim("h1", "r.json", ["eval2"])
    assert target.exists() and ledger.is_spent("h1")
