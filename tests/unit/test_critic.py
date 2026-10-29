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
