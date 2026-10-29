"""Run report (markdown + self-contained HTML with inline SVG charts) and the model card.

Everything shown is read from the run state, which only holds tool outputs. Dataset-derived strings
(column names) are sanitised and HTML-escaped. The headline states planner type and LLM mode.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from harness.agent.models import RunConfig, StepRecord
from harness.policies.untrusted import sanitize_text


def _t(v: object, n: int = 60) -> str:
    return html.escape(sanitize_text(v, n))


def bar_svg(rows: list[tuple[str, float]], title: str, width: int = 520) -> str:
    """Horizontal bar chart; values are scaled to the max absolute value."""
    if not rows:
        return ""
    top = max(abs(v) for _, v in rows) or 1.0
    h = 22 * len(rows) + 30
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {h}" role="img" '
        f'aria-label="{_t(title)}" width="100%">',
        f'<text x="4" y="14" font-size="12" fill="currentColor">{_t(title)}</text>',
    ]
    for i, (label, v) in enumerate(rows):
        y = 26 + 22 * i
        w = max(1.0, (width - 220) * abs(v) / top)
        out.append(
            f'<text x="4" y="{y + 12}" font-size="11" fill="currentColor">{_t(label, 28)}</text>'
        )
        out.append(f'<rect x="150" y="{y}" width="{w:.1f}" height="14" fill="#4c78a8"/>')
        out.append(
            f'<text x="{154 + w:.1f}" y="{y + 12}" font-size="11" '
            f'fill="currentColor">{v:.4g}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def model_card(cfg: RunConfig, state: dict[str, Any]) -> str:
    mid = state.get("final_model_id") or state.get("chosen") or "none"
    m = state.get("models", {}).get(state.get("chosen") or "", {})
    dropped = ", ".join(map(_t, state.get("dropped", []))) or "none"
    return "\n".join(
        [
            f"# Model card: {mid}",
            "",
            f"- Task: {cfg.task.task_type}, metric {cfg.task.metric}, "
            f"target `{_t(cfg.task.target)}`",
            f"- Family: {m.get('family', 'n/a')}; validation {cfg.task.metric}: "
            f"{m.get('val_score', float('nan')):.4f} (seeded holdout of the training file)",
            f"- Dropped columns (leakage/ID policy): {dropped}",
            f"- Unresolved leakage findings: {len(state.get('unresolved', []))}",
            f"- Planner: {cfg.planner}; LLM mode: {cfg.llm_mode}; seed {cfg.task.seed}",
            "- Intended use: tabular prediction on data like the training file. Not validated for "
            "distribution shift. Holdout scores are optimistic relative to the final test score.",
        ]
    )


def write_report(
    cfg: RunConfig, state: dict[str, Any], records: list[StepRecord], out_dir: Path
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    board = state.get("leaderboard", [])
    findings = state.get("findings", [])
    review = state.get("review", {})
    prof = state.get("profile", {})
    missing = sorted(
        ((c["name"], c["missing_frac"]) for c in prof.get("columns", []) if c["missing_frac"] > 0),
        key=lambda x: -x[1],
    )[:10]
    head = (
        f"Run {cfg.run_id} on {_t(cfg.task.name)}: planner={cfg.planner}, llm_mode={cfg.llm_mode}"
        + (" (scripted, no LLM)" if cfg.planner == "scripted" else "")
    )
    lat = [(r.step.tool, r.latency_s) for r in records]
    md = [
        f"# {head}", "",
        f"Rows {prof.get('n_rows', '?')}, columns {prof.get('n_cols', '?')}, "
        f"duplicate rows {prof.get('duplicate_rows', '?')}.", "",
        "## Leakage findings", "",
    ]  # fmt: skip
    md += [
        f"- {f['severity']} {f['type']}: {', '.join(map(_t, f['columns']))}" for f in findings
    ] or ["- none"]
    md += [
        "",
        f"Dropped: {', '.join(map(_t, state.get('dropped', []))) or 'none'}",
        "",
        "## Leaderboard",
        "",
    ]
    md += [f"- {r['model_id']} ({r['family']}): {r['val_score']:.4f}" for r in board] or ["- none"]
    md += ["", f"Reviewer: {review.get('verdict', 'n/a')}"]
    for k, c in review.get("checks", {}).items():
        md.append(f"- {k}: {'pass' if c['passed'] else 'FAIL'} ({_t(c['detail'], 120)})")
    md += ["", "## Steps", ""]
    md += [
        f"- {r.idx} {r.step.server}/{r.step.tool}: {'ok' if r.ok else 'FAILED'} {r.latency_s:.2f}s"
        for r in records
    ]
    card = model_card(cfg, state)
    (out_dir / "model_card.md").write_text(card, encoding="utf-8")
    (out_dir / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    rows = (
        "".join(
            f"<tr><td>{_t(f['severity'])}</td><td>{_t(f['type'])}</td>"
            f"<td>{_t(', '.join(f['columns']), 120)}</td></tr>"
            for f in findings
        )
        or "<tr><td colspan=3>none</td></tr>"
    )
    body = (
        f"<h1>{html.escape(head)}</h1>"
        f"<h2>Data story</h2><p>{prof.get('n_rows', '?')} rows, "
        f"{prof.get('n_cols', '?')} columns.</p>"
        + bar_svg(missing, "Missing fraction (top columns)")
        + "<h2>Leakage findings</h2><table><tr><th>severity</th><th>type</th>"
        + f"<th>columns</th></tr>{rows}</table>"
        + "<h2>Leaderboard</h2>"
        + bar_svg([(r["family"], r["val_score"]) for r in board], f"Validation {cfg.task.metric}")
        + f"<h2>Reviewer: {html.escape(str(review.get('verdict', 'n/a')))}</h2>"
        + "<h2>Step latency</h2>"
        + bar_svg(lat, "Seconds per step")
        + f"<h2>Model card</h2><pre>{html.escape(card)}</pre>"
    )
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Run report {html.escape(cfg.run_id)}</title>"
        "<style>body{font:15px system-ui;max-width:760px;margin:2rem auto;padding:0 16px}"
        "td,th{border:1px solid #8884;padding:2px 8px}</style></head><body>"
        f"{body}</body></html>"
    )
    (out_dir / "report.html").write_text(page, encoding="utf-8")
    return {"md": str(out_dir / "report.md"), "html": str(out_dir / "report.html"),
            "model_card": str(out_dir / "model_card.md")}  # fmt: skip
