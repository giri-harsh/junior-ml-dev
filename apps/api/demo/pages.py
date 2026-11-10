"""Server-rendered pieces of the demo: the plain-English result sentence and the styled report.

The report is built from the run's own state (tool outputs only), not from the generic harness
report, so it can use readable column names and say plainly when a check was skipped. Everything
dataset-derived goes through `esc`; the page carries no script and is served with a strict CSP.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from apps.api.demo.datasets import INFO, label
from apps.api.demo.samples import BY_KEY
from harness.policies.untrusted import sanitize_text

SKIPPED = "Skipped in live demo (CPU limit)"
MEAN = "<b>What this means</b>"
NO_MODEL = "The run finished without a scored model."
HIGHER_IS_BETTER = {"roc_auc", "pr_auc", "f1_macro"}
FONTS = (
    "https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;800"
    "&family=Instrument+Serif:ital@1&family=JetBrains+Mono:wght@400;500&display=swap"
)
# the report may load the Google Fonts stylesheet and files, nothing else; no script runs
REPORT_CSP = (
    "default-src 'none'; style-src 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; img-src data:; sandbox"
)


def esc(v: object, n: int = 80) -> str:
    return html.escape(sanitize_text(v, n))


def _pct(x: float) -> int:
    return int(round(max(0.0, min(1.0, x)) * 100))


def result_sentence(
    sample_key: str, metric: str, score: float | None, top_feature: str | None
) -> str | None:
    """One plain sentence about the winning model, from the metric and the top feature only."""
    if score is None:
        return None
    info = INFO.get(sample_key, {})
    top = (
        f" {sanitize_text(label(sample_key, top_feature), 40)} mattered most."
        if top_feature
        else ""
    )
    if metric == "roc_auc":
        pair = info.get("pair") or "one positive and one negative case"
        return f"Shown {pair}, the model picks the right one {_pct(score)}% of the time.{top}"
    if metric == "pr_auc":
        return (
            f"The model's precision-recall score is {score:.2f} out of 1.00, "
            f"where 1.00 means every positive case is found without false alarms.{top}"
        )
    if metric == "f1_macro":
        return f"The model's balanced F1 score is {score:.2f} out of 1.00.{top}"
    if metric in ("rmse", "mae"):
        unit = info.get("unit") or "units of the target"
        how = "off by about" if metric == "rmse" else "typically off by"
        return f"The model's predictions are {how} {score:.2f} {unit}.{top}"
    return f"The model's validation {metric} is {score:.4g}.{top}"


def top_feature(state: dict[str, Any] | None) -> str | None:
    top = ((state or {}).get("explain") or {}).get("top") or []
    return str(top[0]["feature"]) if top else None


def _bars(rows: list[tuple[str, float, str]], best_first: bool = True) -> str:
    """Amber bars; each row is (label, width fraction 0..1, value text)."""
    out = []
    for i, (name, frac, val) in enumerate(rows):
        w = max(2, min(100, int(round(frac * 100))))
        cls = " best" if (i == 0 and best_first) else ""
        out.append(
            f'<div class="br{cls}"><span class="bn">{esc(name, 40)}</span>'
            f'<span class="bb"><i style="width:{w}%"></i></span>'
            f'<span class="bv">{esc(val, 14)}</span></div>'
        )
    return "".join(out)


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


CSS = (Path(__file__).resolve().parents[2] / "web" / "demo" / "report.css").read_text(
    encoding="utf-8"
)


def _checks_table(review: dict[str, Any], partial: list[str]) -> str:
    rows = []
    for name, c in (review.get("checks") or {}).items():
        ok = bool(c.get("passed"))
        detail = esc(c.get("detail", ""), 140)
        if name == "leakage_checked" and partial:
            status, cls = SKIPPED, "warn"
        else:
            status, cls = ("pass", "ok") if ok else ("FAIL", "bad")
        rows.append(
            f"<tr><td>{esc(name.replace('_', ' '), 40)}</td>"
            f'<td class="{cls}">{status}</td><td>{detail}</td></tr>'
        )
    if not rows:
        return "<p class='mean'>No reviewer checks were recorded.</p>"
    return (
        "<table><tr><th>check</th><th>result</th><th>detail</th></tr>" + "".join(rows) + "</table>"
    )


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
            f"- Family: {m.get('family', 'n/a')}; validation {metric}: "
            + (f"{score:.4f}" if isinstance(score, int | float) else "n/a")
            + " (seeded holdout of the training file)",
            f"- Dropped columns (leakage/ID policy): {dropped}",
            "- Planner: scripted, no LLM. Leakage detectors skipped in the live demo (CPU limit).",
            "- Intended use: tabular prediction on data like this public sample. Not validated "
            "for distribution shift. Holdout scores are optimistic relative to a final test score.",
        ]
    )


def render_report(
    run_id: str, sample_key: str, state: dict[str, Any], summary: dict[str, Any] | None
) -> str:
    """The styled report page (no script, system fonts as a fallback)."""
    s = BY_KEY[sample_key]
    summary = summary or {}
    prof = state.get("profile") or {}
    partial = list(state.get("leakage_partial") or [])
    board = _leaderboard_rows(state.get("leaderboard") or [], s.metric, state.get("models"))
    top = ((state.get("explain") or {}).get("top") or [])[:8]
    imp_max = max([float(i.get("mean_drop", 0.0)) for i in top] or [1.0]) or 1.0
    imp_rows = [
        (
            label(sample_key, str(i["feature"])),
            max(0.0, float(i["mean_drop"])) / imp_max,
            f"{float(i['mean_drop']):.3g}",
        )
        for i in top
    ]
    sentence = result_sentence(sample_key, s.metric, summary.get("val_score"), top_feature(state))
    verdict_raw = sanitize_text((state.get("review") or {}).get("verdict", "n/a"), 30)
    verdict = html.escape(verdict_raw)
    miss = sorted(
        (
            (label(sample_key, str(c["name"])), float(c["missing_frac"]))
            for c in prof.get("columns", [])
            if float(c.get("missing_frac", 0)) > 0
        ),
        key=lambda x: -x[1],
    )[:8]
    dname = INFO.get(sample_key, {}).get("name", s.title)
    leak = (
        f'<span class="skip">{SKIPPED}</span>'
        if partial
        else (
            "<p class='mean'>No leakage findings.</p>"
            if not state.get("findings")
            else "<p class='mean'>Findings: "
            + ", ".join(esc(f.get("type", "?"), 40) for f in state.get("findings", []))
            + "</p>"
        )
    )
    card = model_card_text(sample_key, s.metric, s.task_type, s.target, state)
    kv = [
        ("rows", prof.get("n_rows", "?")),
        ("columns", prof.get("n_cols", "?")),
        ("best model", summary.get("chosen_family") or "n/a"),
        (
            s.metric,
            f"{summary['val_score']:.4g}"
            if isinstance(summary.get("val_score"), int | float)
            else "n/a",
        ),
        ("reviewer", verdict_raw),
        (
            "run time",
            f"{summary['latency_s']:.0f} s"
            if isinstance(summary.get("latency_s"), int | float)
            else "n/a",
        ),
    ]
    kvh = "".join(f"<span>{esc(k, 20)} <b>{esc(v, 40)}</b></span>" for k, v in kv)
    body = (
        f'<p class="k">Run report · {esc(run_id, 20)}</p>'
        f"<h1>{esc(dname, 50)}, <em>explained.</em></h1>"
        f'<div class="sum"><p>{html.escape(sentence or NO_MODEL)}</p>'
        f'<div class="kv">{kvh}</div></div>'
        "<section><h2>The data</h2>"
        f"<p class='mean'><b>What this means</b>{esc(prof.get('n_rows', '?'))} examples with "
        f"{esc(prof.get('n_cols', '?'))} columns were used. Columns with gaps are listed below.</p>"
        + (
            _bars([(n, f, f"{f:.0%}") for n, f in miss], best_first=False)
            or "<p class='mean'>No missing values.</p>"
        )
        + "</section><section><h2>Leakage check</h2>"
        f"<p class='mean'>{MEAN}Leakage is when a column secretly contains the answer. "
        "Catching it keeps the score honest.</p>" + leak + "</section>"
        "<section><h2>Model leaderboard</h2>"
        f"<p class='mean'><b>What this means</b>Each model was scored on data it had not seen "
        f"({esc(s.metric)}, {'higher' if s.metric in HIGHER_IS_BETTER else 'lower'} is better). "
        "A model that barely beats the baseline has found little real signal.</p>"
        + (_bars(board) or "<p class='mean'>No model was scored.</p>")
        + "</section>"
        + (
            "<section><h2>What drove the predictions</h2>"
            f"<p class='mean'>{MEAN}Bars show how much the score drops when a column "
            "is shuffled: the taller the bar, the more the model leans on it.</p>"
            + _bars(imp_rows)
            + "</section>"
            if imp_rows
            else ""
        )
        + "<section><h2>Reviewer checks</h2>"
        f"<p class='mean'>{MEAN}A rule-based reviewer re-checks the work. Verdict: {verdict}.</p>"
        + _checks_table(state.get("review") or {}, partial)
        + "</section><section><h2>Model card</h2>"
        f"<pre>{html.escape(card)}</pre></section>"
        "<p class='f'>Scripted planner, no LLM. Runs on a free 0.1 vCPU server with FLAML and the "
        "leakage detectors switched off; the full pipeline is benchmarked separately.</p>"
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Run report {esc(run_id, 20)}</title>"
        f'<link rel="stylesheet" href="{FONTS}"><style>{CSS}</style></head>'
        f'<body><div class="w">{body}</div></body></html>'
    )


def json_safe(obj: object) -> str:
    return json.dumps(obj).replace("<", "\\u003c")
