"""Server-rendered pieces of the demo: the plain-English result sentence and the styled report.

The report is built from the run's own state (tool outputs only), not from the generic harness
report, so it can use readable column names and say plainly when a check was skipped. Everything
dataset-derived goes through `esc`; the page carries no script and is served with a strict CSP.
"""

from __future__ import annotations

import html
from typing import Any

from apps.api.demo.datasets import INFO, label
from harness.policies.untrusted import sanitize_text

SKIPPED = "Skipped in live demo (CPU limit)"
NO_MODEL = "The run finished without a scored model."
HIGHER_IS_BETTER = {"roc_auc", "pr_auc", "f1_macro"}
FONTS = (
    "https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;800"
    "&family=Instrument+Serif:ital@1&family=JetBrains+Mono:wght@400;500&display=swap"
)
# The report loads only its own stylesheet and scripts (no inline script, no eval, no network
# calls) plus the Google Fonts files. `sandbox` is not used: Chrome does not match 'self' for a
# sandboxed document, and nothing on the page comes from a visitor (bundled samples only).
REPORT_CSP = (
    "default-src 'none'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; script-src 'self'; img-src data:; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
)


def esc(v: object, n: int = 80) -> str:
    return html.escape(sanitize_text(v, n))


def _pct(x: float) -> int:
    return int(round(max(0.0, min(1.0, x)) * 100))


def answer_parts(sample_key: str, metric: str, score: float | None) -> tuple[str, str, str] | None:
    """The main sentence split around its key number: (before, key, after)."""
    if score is None:
        return None
    info = INFO.get(sample_key, {})
    unit = info.get("unit") or "units of the target"
    if metric == "roc_auc":
        pair = info.get("pair") or "one positive and one negative case"
        return (
            f"Shown {pair}, the model picks the right one ",
            f"{_pct(score)}%",
            " of the time.",
        )
    if metric == "accuracy":
        return "The model gets ", f"{_pct(score)}%", " of cases right."
    if metric == "r2":
        return "The model explains ", f"{_pct(score)}%", " of the variation."
    if metric == "pr_auc":
        return "The model's precision-recall score is ", f"{score:.2f}", " out of 1.00."
    if metric == "f1_macro":
        return "The model's balanced F1 score is ", f"{score:.2f}", " out of 1.00."
    if metric == "rmse":
        return "The model's predictions are typically off by about ", f"{score:.2f}", f" {unit}."
    if metric == "mae":
        return "The model's predictions are off by about ", f"{score:.2f}", f" {unit} on average."
    return f"The model's validation {metric} is ", f"{score:.4g}", "."


def result_sentence(
    sample_key: str, metric: str, score: float | None, top_feature: str | None
) -> str | None:
    """One plain sentence about the winning model, from the metric and the top feature only."""
    parts = answer_parts(sample_key, metric, score)
    if parts is None:
        return None
    top = (
        f" {sanitize_text(label(sample_key, top_feature), 40)} mattered most."
        if top_feature
        else ""
    )
    return "".join(parts) + top


def top_feature(state: dict[str, Any] | None) -> str | None:
    top = ((state or {}).get("explain") or {}).get("top") or []
    return str(top[0]["feature"]) if top else None


def _tuned_ids(models: dict[str, Any]) -> set[str]:
    """A family trained twice (the planner tunes boosting) marks the later model as tuned."""
    first: dict[str, str] = {}
    tuned: set[str] = set()
    for mid, m in models.items():
        fam = str(m.get("family"))
        if fam in first:
            tuned.add(mid)
        else:
            first[fam] = mid
    return tuned


def _leaderboard_rows(
    board: list[dict[str, Any]], metric: str, models: dict[str, Any] | None = None
) -> list[tuple[str, float, str]]:
    higher = metric in HIGHER_IS_BETTER
    tuned = _tuned_ids(models or {})
    scored = [r for r in board if isinstance(r.get("val_score"), int | float)]
    scored.sort(key=lambda r: -r["val_score"] if higher else r["val_score"])
    if not scored:
        return []
    vals = [float(r["val_score"]) for r in scored]
    top, best = max(vals), min(vals)
    rows = []
    for r, v in zip(scored, vals, strict=True):
        frac = (v / top if top > 0 else 0.0) if higher else (best / v if v > 0 else 0.0)
        name = str(r.get("family", r.get("model_id", "?")))
        if r.get("model_id") in tuned:
            name += " (tuned)"
        rows.append((name, frac, f"{v:.4g}"))
    return rows


def model_card_text(
    sample_key: str, metric: str, task_type: str, target: str, state: dict[str, Any]
) -> str:
    mid = state.get("final_model_id") or state.get("chosen") or "none"
    m = (state.get("models") or {}).get(state.get("chosen") or "", {})
    score = m.get("val_score")
    dropped = (
        ", ".join(sanitize_text(label(sample_key, str(c)), 40) for c in state.get("dropped", []))
        or "none"
    )
    return "\n".join(
        [
            f"Model card: {sanitize_text(mid, 60)}",
            f"- Task: {task_type}, metric {metric}, target {label(sample_key, target)}",
            f"- Family: {sanitize_text(m.get('family', 'n/a'), 40)}; validation {metric}: "
            + (f"{score:.4f}" if isinstance(score, int | float) else "n/a")
            + " (seeded holdout of the training file)",
            f"- Dropped columns (leakage/ID policy): {dropped}",
            "- Planner: scripted, no LLM. Leakage detectors skipped in the live demo (CPU limit).",
            "- Intended use: tabular prediction on data like this public sample. Not validated "
            "for distribution shift. Holdout scores are optimistic relative to a final test score.",
        ]
    )
