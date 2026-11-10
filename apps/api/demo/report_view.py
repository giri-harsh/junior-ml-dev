"""The styled report: answer, wire diagram, three chart cards, time bar, model card.

Everything shown is read from the run's own state and step records (and, for a regression target's
histogram, the bundled sample file the run used). Strings that came from a dataset go through
`esc`; the page has no inline script, and CSS draws the charts, tooltips and the model-card modal.
"""

from __future__ import annotations

import html
from typing import Any

from apps.api.demo import narration
from apps.api.demo.avatar import avatar_html
from apps.api.demo.datasets import INFO, class_names, label
from apps.api.demo.pages import (
    FONTS,
    HIGHER_IS_BETTER,
    NO_MODEL,
    SKIPPED,
    _leaderboard_rows,
    _tuned_ids,
    answer_parts,
    esc,
    model_card_text,
    top_feature,
)
from apps.api.demo.samples import BY_KEY
from harness.policies.untrusted import sanitize_text

STAGES = ("Profile", "Leakage hunt", "Train", "Compare", "Review", "Explain")
STAGE_OF = {
    "profile_dataset": 0, "detect_leakage": 1, "decide_leakage": 1, "train_model": 2,
    "tune_model": 2, "compare_models": 3, "review": 4, "refit_full": 5, "explain_model": 5,
    "report": 5,
}  # fmt: skip
STAGE_COLORS = ("#6E685F", "#4A443D", "#F2B880", "#8FD9A8", "#A39C92", "#EDE8E1")
DONUT_COLORS = ("#F2B880", "#4A443D", "#8FD9A8", "#6E685F", "#A39C92")
ICONS = {
    "Profile": '<path d="M4 5h16v14H4z"/><path d="M4 10h16M10 5v14"/>',
    "Leakage hunt": '<circle cx="11" cy="11" r="6"/><path d="M16 16l5 5"/>',
    "Train": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    "Compare": '<path d="M5 20V10M12 20V4M19 20v-7"/>',
    "Review": '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    "Explain": '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-4 10c1 1 1 2 1 3h6'
    'c0-1 0-2 1-3a6 6 0 0 0-4-10z"/>',
}  # fmt: skip


def icon(name: str) -> str:
    return (
        '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" '
        f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f"{ICONS[name]}</svg>"
    )


def _secs(v: float) -> str:
    return f"{v:.1f} s" if v >= 0.05 else "<0.1 s"


def _num(v: Any, digits: int = 4) -> str:
    return f"{v:.{digits}g}" if isinstance(v, int | float) else "n/a"


class Ctx:
    """Everything the sections need, derived once from the run state and the step records."""

    def __init__(
        self,
        sample_key: str,
        state: dict[str, Any],
        summary: dict[str, Any],
        steps: list[dict[str, Any]],
        dist: dict[str, Any] | None,
    ) -> None:
        self.key = sample_key
        self.s = BY_KEY[sample_key]
        self.state, self.summary, self.steps, self.dist = state, summary, steps, dist
        self.prof = state.get("profile") or {}
        self.models: dict[str, Any] = state.get("models") or {}
        self.tuned = _tuned_ids(self.models)
        self.partial = list(state.get("leakage_partial") or [])
        self.chosen = state.get("chosen")
        self.higher = self.s.metric in HIGHER_IS_BETTER

    def model_label(self, mid: str) -> str:
        fam = str(self.models.get(mid, {}).get("family", mid))
        return fam + (" (tuned)" if mid in self.tuned else "")

    def by_label(self) -> dict[str, str]:
        return {self.model_label(mid): mid for mid in self.models}

    @property
    def winner_label(self) -> str | None:
        return self.model_label(self.chosen) if self.chosen in self.models else None

    @property
    def baseline(self) -> float | None:
        dummy = [m.get("val_score") for m in self.models.values() if m.get("family") == "dummy"]
        if dummy and isinstance(dummy[0], int | float):
            return float(dummy[0])
        return 0.5 if self.s.metric == "roc_auc" else None

    @property
    def cv_label(self) -> str:
        m = self.models.get(self.chosen or "", {})
        if m.get("selection") == "cv" and m.get("cv_k"):
            return f"{int(m['cv_k'])}-fold CV"
        return "holdout"

    def stage_secs(self) -> list[float]:
        out = [0.0] * len(STAGES)
        for st in self.steps:
            i = STAGE_OF.get(str(st["tool"]))
            if i is not None:
                out[i] += float(st["secs"])
        return out


# --- header, answer ------------------------------------------------------------------------------
def _pills(c: Ctx) -> str:
    verdict = str((c.state.get("review") or {}).get("verdict", ""))
    ok = verdict == "APPROVE"
    run = c.summary.get("latency_s")
    pills = [f'<span class="pill">{esc(INFO.get(c.key, {}).get("name", c.s.title), 40)}</span>']
    if isinstance(run, int | float):
        pills.append(f'<span class="pill">{run:.0f} s run</span>')
    pills.append(
        f'<span class="pill {"ok" if ok else "warn"}">'
        f"{'Reviewer approved' if ok else 'Changes requested'}</span>"
    )
    return '<div class="pills">' + "".join(pills) + "</div>"


def _muted_line(c: Ctx, score: float | None) -> str:
    top = top_feature(c.state)
    bits = []
    if top:
        bits.append(f"{esc(label(c.key, top), 40)} mattered most.")
    base = c.baseline
    if isinstance(score, int | float) and base is not None:
        if c.higher:
            bits.append(
                f"A model that only guesses scores {base:.2f}; this one scores {score:.2f}."
            )
        else:
            bits.append(f"Always guessing the average would be off by {base:.2f}.")
            std = (c.dist or {}).get("std")
            if isinstance(std, int | float) and std > 0:
                r2 = max(0.0, min(1.0, 1 - (score / std) ** 2))
                bits.append(f"That explains about {round(r2 * 100)}% of the variation.")
    return " ".join(bits)


def _answer(c: Ctx, run_id: str) -> str:
    score = c.summary.get("val_score")
    parts = answer_parts(c.key, c.s.metric, score if isinstance(score, int | float) else None)
    if parts is None:
        big, spoken = html.escape(NO_MODEL), NO_MODEL
    else:
        b, k, a = parts
        big = f'{html.escape(b)}<em class="num">{html.escape(k)}</em>{html.escape(a)}'
        spoken = b + k + a
    avatar = avatar_html(small=True, state="done", say=spoken)
    muted = _muted_line(c, score if isinstance(score, int | float) else None)
    return (
        '<section class="answer rv"><div class="atext"><p class="k">The answer</p>'
        f'<p class="big">{big}</p><p class="mut">{muted}</p></div>'
        f'<div class="aav">{avatar}</div></section>'
    )


# --- wire diagram --------------------------------------------------------------------------------
def _node(name: str, secs: str, tip: str, *, cls: str = "", note: str = "") -> str:
    return (
        f'<div class="wn {cls}" role="listitem" tabindex="0">'
        f'<span class="wi">{icon(name) if name in ICONS else ""}</span>'
        f"<b>{esc(name, 24)}</b><i>{esc(note or secs, 30)}</i>"
        f'<span class="tip" role="tooltip">{esc(tip, 260)}</span></div>'
    )


def _model_node(c: Ctx, lab: str, secs: float, ids: dict[str, str]) -> str:
    mid = ids.get(lab)
    m = c.models.get(mid or "", {})
    fit = _secs(float(m.get("fit_s", 0)))
    tip = f"{lab}: {c.s.metric} {_num(m.get('val_score'))} ({c.cv_label}); fit {fit}."
    win = " win" if lab == c.winner_label else ""
    return (
        f'<div class="wn sm{win}" role="listitem" tabindex="0"><b>{esc(lab, 22)}</b>'
        f"<i>{_secs(secs)}</i>"
        f'<span class="tip" role="tooltip">{esc(tip, 220)}</span></div>'
    )


def _wire(c: Ctx) -> str:
    secs = c.stage_secs()
    prof = c.prof
    gaps = sum(1 for col in prof.get("columns", []) if float(col.get("missing_frac", 0)) > 0)
    t_prof = (
        f"{prof.get('n_rows', '?')} rows x {prof.get('n_cols', '?')} columns; "
        f"{prof.get('duplicate_rows', 0)} duplicate rows; {gaps} columns with gaps."
    )
    if c.partial:
        leak = _node(
            "Leakage hunt",
            "",
            "Skipped in this demo: the detectors need more CPU than the free server has.",
            cls="skip",
            note="skipped in demo",
        )  # noqa: E501
    else:
        n = len(c.state.get("findings") or [])
        dropped = ", ".join(
            sanitize_text(label(c.key, str(x)), 30) for x in c.state.get("dropped", [])
        )
        leak = _node("Leakage hunt", _secs(secs[1]), f"{n} findings. Dropped: {dropped or 'none'}.")
    ids = c.by_label()
    seen: set[str] = set()
    train_nodes = []
    for st in c.steps:
        if st["tool"] not in ("train_model", "tune_model") or not st.get("ok", True):
            continue
        lab = str(st["family"] or "model") + (" (tuned)" if st["tool"] == "tune_model" else "")
        if lab in seen:
            continue
        seen.add(lab)
        train_nodes.append(_model_node(c, lab, float(st["secs"]), ids))
    board = _leaderboard_rows(c.state.get("leaderboard") or [], c.s.metric, c.models)
    best = f"{board[0][0]} ({board[0][2]})" if board else "none"
    t_cmp = f"Ranked {len(board)} models by {c.s.metric} ({c.cv_label}); best: {best}."
    rev = c.state.get("review") or {}
    checks = rev.get("checks") or {}
    passed = sum(1 for v in checks.values() if v.get("passed"))
    t_rev = f"Verdict {rev.get('verdict', 'n/a')}; {passed} of {len(checks)} checks passed."
    expl = c.state.get("explain") or {}
    top = top_feature(c.state)
    t_exp = (
        f"Permutation importance on {expl.get('n_eval', '?')} held-out rows; top feature: "
        f"{label(c.key, top) if top else 'n/a'}."
    )
    conn = '<span class="wc" aria-hidden="true"></span>'
    skipc = '<span class="wc off" aria-hidden="true"></span>'
    return (
        '<section class="card rv"><p class="k">What the agent did</p>'
        '<div class="wire" role="list">'
        + _node("Profile", _secs(secs[0]), t_prof)
        + (skipc if c.partial else conn)
        + leak
        + (skipc if c.partial else conn)
        + '<div class="wtrain" role="group" aria-label="Models trained">'
        + "".join(train_nodes)
        + "</div>"
        + conn
        + _node("Compare", _secs(secs[3]), t_cmp, note=f"{c.cv_label} · {_secs(secs[3])}")
        + conn
        + _node("Review", _secs(secs[4]), t_rev)
        + conn
        + _node("Explain", _secs(secs[5]), t_exp)
        + '</div><p class="cap">Each box shows the step\'s real duration. Hover or focus a box for what it did.</p></section>'  # noqa: E501
    )


# --- chart cards ---------------------------------------------------------------------------------
def _chart_models(c: Ctx) -> str:
    rows = _leaderboard_rows(c.state.get("leaderboard") or [], c.s.metric, c.models)
    if not rows:
        return '<div class="card"><p class="k">Which model won?</p><p class="mut">No model was scored.</p></div>'  # noqa: E501
    vals = [float(r[2]) for r in rows]
    axis = 1.0 if c.higher else max(vals) * 1.15 or 1.0
    base = c.baseline
    cols = []
    for i, (name, _frac, val) in enumerate(rows):
        h = max(2.0, min(100.0, float(val) / axis * 100))
        cols.append(
            f'<div class="col{" win" if i == 0 else ""}"><span class="cv">{esc(val, 8)}</span>'
            f'<i style="height:{h:.1f}%"></i><span class="cn">{esc(name, 18)}</span></div>'
        )
    line = ""
    if base is not None and axis:
        pos = max(0.0, min(100.0, base / axis * 100))
        what = "baseline" if c.higher else "always guess the average"
        line = f'<div class="bl" style="bottom:{pos:.1f}%"><span>{what} {base:.2f}</span></div>'
    cap = (
        "Higher is better. The dashed line is what guessing scores."
        if c.higher
        else "Lower is better. The dashed line is the error of always guessing the average."
    )
    return (
        '<div class="card rv"><p class="k">Which model won?</p>'
        f'<div class="cols">{line}{"".join(cols)}</div><p class="cap">{cap}</p></div>'
    )


def _chart_importance(c: Ctx) -> str:
    top = ((c.state.get("explain") or {}).get("top") or [])[:5]
    if not top:
        return '<div class="card"><p class="k">What drove the prediction?</p><p class="mut">No importance was computed.</p></div>'  # noqa: E501
    peak = max(float(i.get("mean_drop", 0)) for i in top) or 1.0
    rows = []
    for i in top:
        raw = str(i["feature"])
        nice = label(c.key, raw)
        w = max(2.0, min(100.0, max(0.0, float(i["mean_drop"])) / peak * 100))
        rawtxt = f'<code class="raw">{esc(raw, 20)}</code>' if nice != raw else ""
        rows.append(
            f'<div class="ib"><span class="in">{esc(nice, 30)}</span>'
            f'<span class="bar"><i style="width:{w:.1f}%"></i></span>{rawtxt}</div>'
        )
    return (
        '<div class="card rv"><p class="k">What drove the prediction?</p>'
        + "".join(rows)
        + '<p class="cap">How much the score drops when that column is shuffled.</p></div>'
    )


def _chart_data(c: Ctx) -> str:
    n_rows, n_cols = c.prof.get("n_rows", "?"), c.prof.get("n_cols", "?")
    target = c.prof.get("target") or {}
    if c.s.task_type == "regression":
        d = c.dist or {}
        counts = d.get("counts") or []
        peak = max(counts or [1]) or 1
        bars = "".join(
            f'<i style="height:{max(3.0, n / peak * 100):.0f}%" title="{n}"></i>' for n in counts
        )
        lo, hi = d.get("min"), d.get("max")
        rng = f"{_num(lo, 3)} to {_num(hi, 3)}"
        viz = f'<div class="hist" aria-label="Target histogram">{bars}</div>'
        tiles = _tiles(("columns", str(n_cols)), ("target range", rng))
        cap = f"How the {esc(label(c.key, c.s.target), 30).lower()} values are spread."
    else:
        names = class_names(c.key)
        bal = target.get("class_balance") or {}
        stops, legend, acc = [], [], 0.0
        for i, (k, frac) in enumerate(sorted(bal.items())):
            col = DONUT_COLORS[i % len(DONUT_COLORS)]
            f = float(frac)
            stops.append(f"{col} {acc * 100:.2f}% {(acc + f) * 100:.2f}%")
            acc += f
            nm = names.get(str(k), f"class {k}")
            legend.append(f'<li><i style="background:{col}"></i>{esc(nm, 24)} <b>{f:.0%}</b></li>')
        grad = ", ".join(stops) or "#2E2B28 0 100%"
        viz = (
            f'<div class="donut" style="--g:conic-gradient({grad})"><div><b>{esc(n_rows, 8)}</b>'
            f"<span>rows</span></div></div><ul class='leg'>{''.join(legend)}</ul>"
        )
        tiles = _tiles(("columns", str(n_cols)), ("classes", str(target.get("n_classes", "?"))))
        cap = "Share of each outcome in the data the agent saw."
    return (
        f'<div class="card rv"><p class="k">What was in the data?</p>{viz}{tiles}'
        f'<p class="cap">{cap}</p></div>'
    )


def _tiles(*pairs: tuple[str, str]) -> str:
    return (
        '<div class="tiles">'
        + "".join(f"<div><b>{esc(v, 20)}</b><span>{esc(k, 16)}</span></div>" for k, v in pairs)
        + "</div>"
    )


# --- time, buttons, model card -------------------------------------------------------------------
def _time(c: Ctx) -> str:
    secs = c.stage_secs()
    total = sum(secs) or 1.0
    big = max(range(len(secs)), key=lambda i: secs[i])
    segs, legend = [], []
    for i, v in enumerate(secs):
        if v <= 0:
            continue
        pct = v / total * 100
        segs.append(
            f'<i style="width:{pct:.2f}%;background:{STAGE_COLORS[i]}" '
            f'title="{STAGES[i]} {_secs(v)}"></i>'
        )
        legend.append(
            f'<li><i style="background:{STAGE_COLORS[i]}"></i>{STAGES[i]} <b>{_secs(v)}</b></li>'
        )
    title = f"{STAGES[big]} took {round(secs[big] / total * 100)}% of the time"
    skip = " The leakage hunt was skipped in this demo." if c.partial else ""
    return (
        '<section class="card rv"><p class="k">Where the time went</p>'
        f"<h2>{html.escape(title)}</h2>"
        f'<div class="stack">{"".join(segs)}</div><ul class="leg row">{"".join(legend)}</ul>'
        f'<p class="cap">Sum of the {len(c.steps)} step durations ({_secs(total)}).{skip}</p>'
        "</section>"
    )


def _footer(c: Ctx) -> str:
    card = model_card_text(c.key, c.s.metric, c.s.task_type, c.s.target, c.state)
    return (
        '<div class="btns"><a class="btn pri" href="/#datasets">Try another dataset</a>'
        '<a class="btn gho" href="#model-card">Model card</a></div>'
        '<p class="fine">Scripted planner, no LLM, on a free 0.1 vCPU server with FLAML and the '
        "leakage detectors switched off. The full pipeline is benchmarked separately.</p>"
        '<div class="modal" id="model-card" role="dialog" aria-label="Model card">'
        '<div class="mc"><a class="x" href="#" aria-label="Close">&times;</a>'
        f"<pre>{html.escape(card)}</pre></div></div>"
    )


def render_report(
    run_id: str,
    sample_key: str,
    state: dict[str, Any],
    summary: dict[str, Any] | None,
    steps: list[dict[str, Any]] | None = None,
    dist: dict[str, Any] | None = None,
) -> str:
    c = Ctx(sample_key, state, summary or {}, steps or [], dist)
    name = INFO.get(sample_key, {}).get("name", c.s.title)
    body = (
        _pills(c)
        + f'<h1>{esc(name, 50)}, <em class="ser">explained.</em></h1>'
        + _answer(c, run_id)
        + _wire(c)
        + '<div class="grid3">'
        + _chart_models(c)
        + _chart_importance(c)
        + _chart_data(c)
        + "</div>"
        + _time(c)
        + _footer(c)
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Run report {esc(run_id, 20)}</title>"
        f'<link rel="stylesheet" href="{FONTS}">'
        '<link rel="stylesheet" href="/demo-assets/avatar.css">'
        '<link rel="stylesheet" href="/demo-assets/report.css"></head>'
        '<body><div class="w"><p class="eyebrow"><a href="/">Junior ML Dev</a> · '
        f"run {esc(run_id, 20)}</p>"
        f'{body}</div><div id="narr" hidden data-v="{narration.page_data()}"></div>'
        '<script src="/demo-assets/report.js"></script>'
        '<script src="/demo-assets/avatar.js"></script></body></html>'
    )


__all__ = ["SKIPPED", "render_report"]
