"""The fresh critic set v2 is deterministic, hash-pinned, covers every blocker type, and every
`rule_fail_baseline_margin` item truly fails the real check (no numeric dissent can be right)."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from benchmarks.critic_v2 import eval as ev
from benchmarks.critic_v2 import gen
from harness.agent.critic import enrich_v3
from harness.review.checks import (
    check_baseline_margin,
    check_metric_matches_task,
    check_train_val_gap,
)

# Committed BEFORE any critic call read the set. Changing the generator changes this: that is
# the point (a re-generated set would no longer be the one that was hash-committed).
PINNED_SHA256 = "bfdcaf09a5aa03463394a799311f9cf150a68d3abaef55d4c8ca0104415bf628"


def _items() -> list[dict[str, Any]]:
    body = gen.OUT.read_text(encoding="utf-8").replace("\r\n", "\n")
    items: list[dict[str, Any]] = json.loads(body)["items"]
    return items


def _by(planted: str | None) -> list[dict[str, Any]]:
    return [i for i in _items() if i["planted"] == planted]


def _linear(s: dict[str, Any]) -> float:
    return float(next(m["cv"] for m in s["tried"] if m["family"] == "linear"))


def test_regenerates_to_the_committed_bytes_and_hash() -> None:
    body = gen.render(gen.build())
    assert hashlib.sha256(body.encode()).hexdigest() == PINNED_SHA256
    on_disk = gen.OUT.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert on_disk == body
    assert gen.SHA.read_text(encoding="utf-8").strip() == PINNED_SHA256
    assert gen.build() == gen.build()  # deterministic


def test_new_seed_distinct_from_run7() -> None:
    assert gen.SEED != 7001
    assert json.loads(gen.OUT.read_text(encoding="utf-8"))["seed"] == gen.SEED


def test_counts_and_ids() -> None:
    items = _items()
    planted = [i for i in items if i["planted"]]
    assert len(items) >= 50
    assert len(planted) >= 20
    assert len(items) - len(planted) >= 30
    assert (len(items), len(planted)) == (53, 23)
    ids = [i["id"] for i in items]
    assert len(set(ids)) == len(ids)
    assert all(i["planted"] not in ("", None) or i["planted"] is None for i in items)
    # the label lives next to the summary, never inside it
    assert all("planted" not in i["summary"] for i in items)


def test_every_blocker_type_is_covered_at_least_twice() -> None:
    c = Counter(i["planted"] for i in _items() if i["planted"])
    assert set(c) == set(gen.PLANTED_TYPES)
    assert all(n >= 2 for n in c.values()), c
    assert c["rule_fail_baseline_margin"] >= 4  # the flaw of run 7 gets the most items


def test_planted_items_really_show_their_issue() -> None:
    for it in _items():
        s = enrich_v3(it["summary"])
        ch, t = s["chosen"], it["planted"]
        if t == "unresolved_leakage":
            assert s["unresolved_leakage"] and "leakage_resolved" in s["failed_rule_checks"]
        elif t == "leakage_not_run":
            assert s["leakage_detection_ran"] is False
        elif t == "gap_beyond_family_range":
            assert ch["gap_over_range_top"] >= 1.8
        elif t == "tiny_test":
            assert s["small_sample"] is True
        elif t == "cv_instability":
            assert ch["cv_se_ratio"] > 0.2 and ch["lift_over_dummy_se"] >= 1
        elif t == "partial_leakage_check":
            assert s["leakage_coverage"] == "incomplete"
        elif t == "metric_task_mismatch":
            assert s["failed_rule_checks"] == ["metric_matches_task"]
        elif t == "lift_below_one":
            assert ch["lift_over_dummy_se"] < 1
        elif t == "rule_fail_baseline_margin":
            assert s["failed_rule_checks"] == ["baseline_margin"]
        else:
            assert t is None


def test_clean_items_have_no_blocker_condition() -> None:
    for it in _by(None):
        s = enrich_v3(it["summary"])
        ch = s["chosen"]
        assert s["failed_rule_checks"] == [], it["id"]
        assert not s["unresolved_leakage"] and s["leakage_detection_ran"] is True
        assert s["leakage_coverage"] in {"full", "sampled_rows"}
        assert s["small_sample"] is False
        assert ch["cv_se_ratio"] <= 0.2 and ch["lift_over_dummy_se"] >= 1
        assert ch["gap_over_range_top"] <= 1.0
        assert s["failed_steps"] == 0


def test_clean_set_includes_the_benign_edge_cases() -> None:
    clean = [enrich_v3(i["summary"]) for i in _by(None)]
    high = [s for s in clean if s["chosen"]["gap_over_range_top"] >= 0.7]  # in-range high gaps
    assert len(high) >= 5
    assert {s["chosen_family"] for s in high} == {
        "hgb", "rf", "flaml"
    }  # fmt: skip
    assert sum(s["leakage_coverage"] == "sampled_rows" for s in clean) >= 3
    assert sum(200 <= (s["n_rows"] or 0) <= 350 for s in clean) >= 3  # small but ok
    assert sum(s["budget_exhausted"] for s in clean) >= 2
    assert sum(0.1 <= s["chosen"]["cv_se_ratio"] <= 0.2 for s in clean) >= 3  # noisy but fine


def test_rule_checks_are_the_real_check_functions_for_every_item() -> None:
    for it in _items():
        s = it["summary"]
        ch = s["chosen"]
        want = {
            "baseline_margin": check_baseline_margin(ch["cv"], _linear(s), 0.5, s["metric"]).passed,
            "train_val_gap": check_train_val_gap(ch["train"], ch["cv"]).passed,
            "metric_matches_task": check_metric_matches_task(s["metric"], s["task_type"]).passed,
        }
        got = s["rule_checks"]
        assert {k: got[k] for k in want} == want, it["id"]
        assert got["leakage_checked"] is s["leakage_detection_ran"]
        assert got["leakage_resolved"] is (not s["unresolved_leakage"])


def test_every_rule_fail_baseline_item_truly_fails_the_real_check() -> None:
    items = _by("rule_fail_baseline_margin")
    assert len(items) >= 4
    for it in items:
        s = it["summary"]
        ch, lin = s["chosen"], _linear(s)
        res = check_baseline_margin(ch["cv"], lin, 0.5, s["metric"])
        assert res.passed is False and s["rule_checks"]["baseline_margin"] is False
        # unambiguous, not merely "below the 2 % threshold": the agent never beats linear, so a
        # numeric dissent ("it is ahead of the linear model") would be wrong
        assert ch["cv"] <= lin
        assert ch["cv"] < lin * 1.02
        assert ch["cv"] > 0.5 * 1.02  # above the dummy: only the linear comparison fails
        assert lin < 0.98  # the ceiling clause cannot rescue it
        # every OTHER rule passes, so the failure is the only thing to answer
        assert [k for k, ok in s["rule_checks"].items() if not ok] == ["baseline_margin"]
    assert any(
        _linear(i["summary"]) - i["summary"]["chosen"]["cv"] >= 3 * i["summary"]["chosen"]["se"]
        for i in items
    )


def test_all_clean_items_pass_the_real_baseline_check_with_margin() -> None:
    for it in _by(None):
        s = it["summary"]
        assert check_baseline_margin(s["chosen"]["cv"], _linear(s), 0.5, s["metric"]).passed
        assert s["chosen"]["cv"] >= _linear(s) * 1.03 - 1e-4  # a real, not borderline, margin


# --- the evaluation script (no LLM involved) ---------------------------------------------------
def test_eval_verifies_the_hash(tmp_path: Path) -> None:
    assert len(ev.load_set()) == 53
    bad = tmp_path / "set_v2.json"
    bad.write_text(gen.OUT.read_text(encoding="utf-8") + " ", encoding="utf-8")
    bad.with_suffix(".sha256").write_text(PINNED_SHA256, encoding="utf-8")
    with pytest.raises(SystemExit, match="sha256"):
        ev.load_set(bad)


def test_eval_check_mode_makes_no_call(capsys: pytest.CaptureFixture[str]) -> None:
    assert ev.main(["--check"]) == 0
    assert "'planted': 23" in capsys.readouterr().out


def test_eval_refuses_a_second_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / f"{ev.RESULT_NAME}.json").write_text(
        json.dumps({"results": {"no_output": 0}}), encoding="utf-8"
    )
    monkeypatch.setattr(ev, "RESULT_DIR", tmp_path)
    with pytest.raises(SystemExit, match="evaluated once"):
        ev.main([])
    with pytest.raises(SystemExit, match="evaluated once"):
        ev.main(["--complete"])  # nothing is missing, so nothing to complete


class _V:
    def __init__(self, verdict: str, dissent: list[str] | None = None) -> None:
        self.verdict = verdict
        self.defaulted_to_rules: list[str] = []
        self.dissent = [type("D", (), {"check": c}) for c in (dissent or [])]
        self.concerns: list[Any] = []


def test_run_items_paces_only_uncached_requests_and_scores() -> None:
    items = ev.load_set()[:6]
    calls = {"n": 0}
    slept: list[float] = []

    def review(summary: dict[str, Any]) -> Any:
        if summary is items[1]["summary"] or summary is items[3]["summary"]:
            calls["n"] += 1  # an uncached request
        return (
            None if summary is items[5]["summary"] else _V("REQUEST_CHANGES", ["baseline_margin"])
        )

    rows = ev.run_items(items, review, lambda: calls["n"], pace_s=6.0, sleep=slept.append)
    assert slept == [6.0, 6.0] and len(rows) == 6 and rows[5]["critic"] is None
    sc = ev.score(rows)
    assert sc["no_output"] == 1
    assert sc["planted_n"] + sc["clean_n"] == 5


def test_vs_run7_is_marked_not_paired() -> None:
    out = ev.vs_run7({"recall": 3, "planted_n": 23, "false_alarms": 1, "clean_n": 30})
    assert "not paired" in out["note"] and out["run7"]["recall"] == "10/15"
    assert out["run9"]["recall"] == "3/23"


def test_budget_denial_aborts_and_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, ...]] = []

    class R:
        def __init__(self, rc: int) -> None:
            self.returncode = rc

    def fake(*a: str) -> R:
        sent.append(a)
        return R(1 if a[:2] == ("reserve", "gemini") else 0)

    monkeypatch.setattr(ev, "_budget", fake)
    with pytest.raises(SystemExit, match="budget denied"):
        ev.reserve(60)
    assert ("commit", "groq", "0", "60") in sent  # the groq reservation was released
    assert ev.MAX_REQUESTS <= 60
