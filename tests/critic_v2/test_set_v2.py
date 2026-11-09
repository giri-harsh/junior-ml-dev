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


# --- the real main() path with a fake gateway/critic (no network, no budget file) ---------------
class _GW:
    def __init__(self) -> None:
        self.stats = {"calls": 0, "cache_hits": 4, "fixture_hits": 9}
        self.error_statuses: dict[str, int] = {"429": 1}
        self.max_requests: int | None = None


def _patch_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    prior_used: int | None,
    new_calls: int,
    n_missing: int = 6,
    answer_first: int = 10_000,
) -> tuple[list[tuple[str, ...]], _GW]:
    import functools

    gw = _GW()
    sent: list[tuple[str, ...]] = []

    class R:
        returncode = 0

    class Critic:
        n = 0

        def review_v3(self, summary: dict[str, Any]) -> Any:
            if Critic.n < new_calls:  # only these reviews are uncached requests
                gw.stats["calls"] += 1
            Critic.n += 1
            return _V("APPROVE") if Critic.n <= answer_first else None

    monkeypatch.setattr(ev, "RESULT_DIR", tmp_path)
    monkeypatch.setattr(ev, "_budget", lambda *a: (sent.append(a), R())[1])
    monkeypatch.setattr(ev, "_usage", lambda: {"groq": 10, "gemini": 20})
    monkeypatch.setattr(ev, "build_gateway", lambda: gw)
    monkeypatch.setattr(ev, "make_critic", lambda g: Critic())
    monkeypatch.setattr(ev, "run_items", functools.partial(ev.run_items, sleep=lambda s: None))
    if prior_used is not None:
        _write_prior(tmp_path, prior_used, n_missing)
    return sent, gw


def _prior_results(used: int, n_missing: int) -> dict[str, Any]:
    rows = [
        {
            "id": it["id"], "planted": it["planted"], "rule_failed": [],
            "critic": None if k < n_missing else "REQUEST_CHANGES" if it["planted"] else "APPROVE",
            "defaulted_to_rules": [], "dissent": [], "concerns": [],
        }
        for k, it in enumerate(ev.load_set())
    ]  # fmt: skip
    return {
        **ev.score(rows), "set_sha256": "x", "forced_concurrence": 0, "requests_used": used,
        "requests_first_pass": used, "requests_this_pass": used, "max_requests": 60,
        "gateway_stats": {"calls": used, "cache_hits": 0, "fixture_hits": 0},
        "error_statuses": {"500": 2}, "rows": rows,
    }  # fmt: skip


def _write_prior(tmp_path: Path, used: int, n_missing: int) -> None:
    doc = {"date": "d0", "git_sha": "s0", "results": _prior_results(used, n_missing)}
    (tmp_path / f"{ev.RESULT_NAME}.json").write_text(json.dumps(doc), encoding="utf-8")


def _load(tmp_path: Path) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(
        (tmp_path / f"{ev.RESULT_NAME}.json").read_text(encoding="utf-8")
    )
    return out


def test_complete_pass_cannot_overrun_the_total_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent, gw = _patch_main(monkeypatch, tmp_path, prior_used=55, new_calls=4)
    assert ev.main(["--complete"]) == 0
    assert gw.max_requests == ev.MAX_REQUESTS - 55 == 5  # the gateway hard cap
    assert [a for a in sent if a[0] == "reserve"] == [
        ("reserve", "groq", "5"),
        ("reserve", "gemini", "5"),
    ]
    res = _load(tmp_path)["results"]
    # `calls` already excludes cache/fixture hits: the 4 + 9 hits must not be subtracted again
    assert res["requests_this_pass"] == 4 and res["requests_used"] == 59
    assert res["requests_first_pass"] == 55 and res["requests_used"] <= ev.MAX_REQUESTS
    assert ("commit", "groq", "0", "5") in sent and ("commit", "gemini", "0", "5") in sent
    # a repeat with the cap already spent must not run again
    _write_prior(tmp_path, ev.MAX_REQUESTS, 3)
    with pytest.raises(SystemExit, match="request cap spent"):
        ev.main(["--complete"])


def test_completion_keeps_first_pass_numbers_and_runs_only_missing_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent, gw = _patch_main(monkeypatch, tmp_path, prior_used=45, new_calls=6, n_missing=8)
    before = _load(tmp_path)["results"]
    assert before["no_output"] == 8
    seen: list[int] = []
    orig = ev.run_items

    def spy(items: list[dict[str, Any]], *a: Any, **k: Any) -> Any:
        seen.append(len(items))
        return orig(items, *a, **k)

    monkeypatch.setattr(ev, "run_items", spy)
    assert ev.main(["--complete"]) == 0
    assert seen == [8]  # ONLY the no-output items were reviewed
    assert gw.max_requests == 15 == ev.MAX_REQUESTS - 45  # <= COMPLETION_CAP and the total cap
    assert [a for a in sent if a[0] == "reserve"] == [
        ("reserve", "groq", "15"),
        ("reserve", "gemini", "15"),
    ]
    doc = _load(tmp_path)
    res = doc["results"]
    # first-pass fields are preserved verbatim, completed numbers are on top
    assert res["first_pass"] == before
    assert res["first_pass_meta"] == {"date": "d0", "git_sha": "s0"}
    assert (res["first_pass"]["recall"], res["first_pass"]["planted_n"]) == (
        before["recall"], before["planted_n"],
    )  # fmt: skip
    assert res["no_output"] == 0 and res["planted_n"] + res["clean_n"] == 53
    assert res["completion"]["label"] == "completion"
    assert res["completion"]["still_no_output"] == [] and len(res["completion"]["filled_ids"]) == 8
    assert res["requests_used"] == 51 and res["requests_first_pass"] == 45
    assert res["requests_this_pass"] == 6 and res["completion"]["requests_used"] == 6


def test_completion_pass_two_keeps_the_original_first_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_main(monkeypatch, tmp_path, 45, new_calls=2, n_missing=8, answer_first=5)
    first = _load(tmp_path)["results"]
    assert ev.main(["--complete"]) == 0
    mid = _load(tmp_path)["results"]
    assert mid["no_output"] == 3 and len(mid["completion"]["still_no_output"]) == 3
    assert mid["first_pass"] == first
    _patch_main(monkeypatch, tmp_path, None, new_calls=1, n_missing=0)
    assert ev.main(["--complete"]) == 0
    end = _load(tmp_path)["results"]
    assert end["first_pass"] == first and end["no_output"] == 0
    assert end["requests_used"] == 45 + 2 + 1 and end["completion"]["requests_used"] == 3


def test_first_pass_records_requests_and_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, gw = _patch_main(monkeypatch, tmp_path, prior_used=None, new_calls=7)
    assert ev.main([]) == 0
    assert gw.max_requests == ev.MAX_REQUESTS
    res = json.loads((tmp_path / f"{ev.RESULT_NAME}.json").read_text(encoding="utf-8"))["results"]
    assert res["requests_used"] == res["requests_first_pass"] == res["requests_this_pass"] == 7
    assert "not paired" in res["vs_run7"]["note"]


def test_failed_gateway_construction_releases_the_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent, _ = _patch_main(monkeypatch, tmp_path, prior_used=None, new_calls=0)

    def boom() -> Any:
        raise RuntimeError("missing GROQ_API_KEY")

    monkeypatch.setattr(ev, "build_gateway", boom)
    with pytest.raises(RuntimeError, match="missing"):
        ev.main([])
    n = str(ev.MAX_REQUESTS)
    assert ("reserve", "groq", n) in sent and ("reserve", "gemini", n) in sent
    assert ("commit", "groq", "0", n) in sent and ("commit", "gemini", "0", n) in sent
    assert not (tmp_path / f"{ev.RESULT_NAME}.json").exists()
