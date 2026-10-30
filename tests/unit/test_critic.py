from __future__ import annotations

import json

from harness.agent.critic import LLMCritic, run_summary
from harness.agent.models import RunConfig, RunTask
from harness.gateway.gateway import Gateway
from harness.gateway.models import LLMRequest
from harness.gateway.providers import MockProvider

CFG = RunConfig(
    run_id="r",
    task=RunTask(
        name="t", data_path="x", target="secret_target_name", task_type="binary", metric="roc_auc"
    ),
)
STATE = {
    "models": {
        "l": {
            "family": "linear",
            "val_score": 0.9,
            "train_score": 0.91,
            "cv_se": 0.01,
            "scored": True,
        },
        "h": {
            "family": "hgb",
            "val_score": 0.92,
            "train_score": 1.0,
            "cv_se": 0.01,
            "scored": True,
        },
    },
    "chosen": "h",
    "failures": {"detect_leakage": "GuardError: timeout"},
    "unresolved": ["group_leakage:somecolumn"],
    "dropped": ["a", "b"],
}


def test_summary_is_symbolic_and_hides_column_names() -> None:
    s = run_summary(CFG, STATE)
    blob = json.dumps(s)
    assert "secret_target_name" not in blob and "somecolumn" not in blob
    assert s["leakage_detection_ran"] is False and s["unresolved_leakage"] == ["group_leakage"]
    assert s["chosen_family"] == "hgb" and s["dropped_columns"] == 2


def test_critic_returns_a_structured_verdict_and_survives_garbage() -> None:
    seen: list[LLMRequest] = []

    def good(req: LLMRequest, i: int) -> str:
        seen.append(req)
        return json.dumps({"verdict": "REQUEST_CHANGES", "concerns": ["leakage check did not run"]})

    v = LLMCritic(Gateway(providers=[MockProvider(good)])).review(run_summary(CFG, STATE))
    assert v is not None and v.verdict == "REQUEST_CHANGES" and "leakage" in v.concerns[0]
    assert "REQUEST_CHANGES" not in seen[0].messages[1].content  # it never sees a rule verdict
    bad = Gateway(providers=[MockProvider(lambda r, i: "no json")], sleep=lambda s: None)
    assert LLMCritic(bad).review(run_summary(CFG, STATE)) is None


def test_v2_summary_is_family_aware_and_symbolic() -> None:
    from harness.agent.critic import load_family_gaps, run_summary_v2

    state = {
        "models": {
            "d": {
                "family": "dummy",
                "val_score": 0.5,
                "train_score": 0.5,
                "cv_se": 0.0,
                "scored": True,
            },
            "h": {
                "family": "hgb",
                "val_score": 0.90,
                "train_score": 1.0,
                "cv_se": 0.01,
                "scored": True,
            },
        },
        "chosen": "h",
        "profile": {"n_rows": 1234},
        "unresolved": ["group_leakage:secretcol"],
    }
    gaps = {"hgb": {"range": [0.01, 1.4]}}
    s = run_summary_v2(
        CFG, state, {"leakage_resolved": {"passed": False, "detail": "x:secretcol"}}, gaps
    )
    blob = json.dumps(s)
    assert "secretcol" not in blob and "secret_target_name" not in blob
    c = s["chosen"]
    assert c["family"] == "hgb" and c["expected_gap_ratio"] == [0.01, 1.4]
    assert c["gap_ratio"] == 0.25 and c["lift_over_dummy_se"] == 40.0 and s["n_rows"] == 1234
    assert s["rule_checks"] == {"leakage_resolved": False}
    assert set(load_family_gaps()) >= {"hgb", "rf", "linear"}  # derived from dev runs, committed


def test_v2_verdict_comes_only_from_blockers() -> None:
    from harness.agent.critic import Concern, CriticVerdictV2, LLMCriticV2

    notes = CriticVerdictV2(concerns=[Concern(text="gap inside range", severity="note")])
    assert notes.verdict == "APPROVE" and CriticVerdictV2().verdict == "APPROVE"
    blk = CriticVerdictV2(
        concerns=[Concern(text="x", severity="note"), Concern(text="y", severity="blocker")]
    )
    assert blk.verdict == "REQUEST_CHANGES"
    reply = json.dumps({"concerns": [{"text": "leakage unresolved", "severity": "blocker"}]})
    gw = Gateway(providers=[MockProvider(lambda r, i: reply)])
    v = LLMCriticV2(gw).review_v2({"a": 1})
    assert v is not None and v.verdict == "REQUEST_CHANGES"


def _v3_summary(failed: bool = True) -> dict[str, object]:
    return {
        "tried": [{"family": "dummy", "cv": 0.5, "se": 0.0, "train": 0.5}],
        "chosen": {"cv": 0.8, "se": 0.1, "gap_ratio": 3.0, "expected_gap_ratio": [0.0, 1.0]},
        "leakage_partial": ["detector skipped: time bound"],
        "n_rows": 120,
        "rule_checks": {"baseline_margin": not failed, "leakage_resolved": True},
    }


def test_v3_enrichment_derives_fields_from_the_summary_numbers() -> None:
    from harness.agent.critic import enrich_v3

    e = enrich_v3(_v3_summary())
    assert e["failed_rule_checks"] == ["baseline_margin"] and e["small_sample"] is True
    assert e["leakage_coverage"] == "incomplete"
    assert e["chosen"]["cv_se_ratio"] == 0.333 and e["chosen"]["gap_over_range_top"] == 3.0
    assert enrich_v3({"leakage_partial": ["rows sampled to 20000"]})["leakage_coverage"] == (
        "sampled_rows"
    )


def test_v3_rejects_silent_approval_repairs_once_then_concurs_by_default() -> None:
    from harness.agent.critic import LLMCriticV3

    silent = json.dumps({"concerns": []})
    gw = Gateway(providers=[MockProvider(lambda r, i: silent)])
    v = LLMCriticV3(gw).review_v3(_v3_summary())
    assert v is not None and v.verdict == "REQUEST_CHANGES"
    assert v.defaulted_to_rules == ["baseline_margin"]
    assert gw.stats["repairs"] == 1  # exactly one repair, then the default


def test_v3_accepts_concurrence_or_numeric_dissent_but_not_vague_dissent() -> None:
    from harness.agent.critic import LLMCriticV3

    concur = json.dumps(
        {"concerns": [{"text": "x", "severity": "blocker", "check": "baseline_margin"}]}
    )
    v = LLMCriticV3(Gateway(providers=[MockProvider(lambda r, i: concur)])).review_v3(_v3_summary())
    assert v is not None and v.verdict == "REQUEST_CHANGES" and not v.defaulted_to_rules
    ok = json.dumps(
        {"concerns": [], "dissent": [{"check": "baseline_margin",
                                      "evidence": "margin 0.0137 over linear is 4.5 se, large"}]}
    )  # fmt: skip
    v = LLMCriticV3(Gateway(providers=[MockProvider(lambda r, i: ok)])).review_v3(_v3_summary())
    assert v is not None and v.verdict == "APPROVE" and not v.defaulted_to_rules
    vague = json.dumps({"concerns": [], "dissent": [{"check": "baseline_margin",
                                                    "evidence": "the rule seems too strict here"}]})  # fmt: skip
    v = LLMCriticV3(Gateway(providers=[MockProvider(lambda r, i: vague)])).review_v3(_v3_summary())
    assert v is not None and v.defaulted_to_rules == ["baseline_margin"]


def test_v3_without_failed_checks_needs_no_answer() -> None:
    from harness.agent.critic import LLMCriticV3

    reply = json.dumps({"concerns": [{"text": "n small", "severity": "blocker"}]})
    v = LLMCriticV3(Gateway(providers=[MockProvider(lambda r, i: reply)])).review_v3(
        _v3_summary(failed=False)
    )
    assert v is not None and v.verdict == "REQUEST_CHANGES"


def test_fresh_critic_set_is_hash_committed_and_sized() -> None:
    from benchmarks.critic_eval_v6 import load_set, score

    items = load_set()  # raises if the file no longer matches its committed sha256
    planted = [i for i in items if i["planted"]]
    assert len(items) >= 30 and len(planted) >= 10 and len(items) - len(planted) >= 20
    assert {i["planted"] for i in planted} >= {
        "unresolved_leakage", "gap_beyond_family_range", "tiny_test", "cv_instability",
        "partial_leakage_check",
    }  # fmt: skip
    rows = [{"planted": "a", "critic": "REQUEST_CHANGES"}, {"planted": None, "critic": "APPROVE"},
            {"planted": "a", "critic": None}]  # fmt: skip
    s = score(rows)
    assert (
        s["recall"] == 1 and s["planted_n"] == 1 and s["false_alarms"] == 0 and s["no_output"] == 1
    )
