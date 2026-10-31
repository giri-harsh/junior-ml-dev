"""PDF report generation via WeasyPrint (PRD S21.3).

Stakeholder-focused single-page PDF with verified numbers and ≤3 charts. This is a NEW module
that works alongside the existing HTML/MD report generation in report.py.
"""

from __future__ import annotations

import html
from io import BytesIO
from pathlib import Path
from typing import Any

from weasyprint import HTML  # type: ignore[import-untyped]

from harness.agent.models import RunConfig
from harness.policies.untrusted import sanitize_text


def _t(v: object, n: int = 60) -> str:
    """Sanitize and HTML-escape untrusted text."""
    return html.escape(sanitize_text(v, n))


def _format_metric(metric: str, value: float) -> str:
    """Format metric in business-friendly terms (PRD S21.3: business-term metrics)."""
    terms = {
        "roc_auc": ("Model accuracy score", "higher is better"),
        "pr_auc": ("Precision-recall score", "higher is better"),
        "f1_macro": ("F1 score", "higher is better"),
        "rmse": ("Prediction error (RMSE)", "lower is better"),
        "mae": ("Average prediction error", "lower is better"),
    }
    name, direction = terms.get(metric, (metric, ""))
    return f"{name}: {value:.3f}" + (f" ({direction})" if direction else "")


def generate_pdf(
    cfg: RunConfig,
    state: dict[str, Any],
    out_path: Path,
) -> None:
    """Generate single-page stakeholder PDF from run state (PRD S21.3).
    
    All numbers are computed deterministically from state (no LLM-generated claims).
    Charts limited to ≤3 for single-page constraint.
    
    Args:
        cfg: Run configuration
        state: Run state dict (from write_report context)
        out_path: Output PDF path
    
    Raises:
        ValueError: If generated PDF is not exactly 1 page (PRD acceptance criterion)
    """
    # Extract verified data from state
    board = state.get("leaderboard", [])
    findings = state.get("findings", [])
    review = state.get("review", {})
    prof = state.get("profile", {})
    expl = state.get("explain") or {}
    
    # Select best model
    chosen = state.get("chosen") or (board[0]["model_id"] if board else "none")
    chosen_model = next((m for m in board if m["model_id"] == chosen), {})
    
    # Business metrics (verified from state, not generated)
    n_rows = prof.get("n_rows", "?")
    n_cols = prof.get("n_cols", "?")
    val_score = chosen_model.get("val_score", float("nan"))
    family = chosen_model.get("family", "n/a")
    
    # Leakage summary
    n_findings = len(findings)
    high_severity = sum(1 for f in findings if f.get("severity") == "high")
    
    # Top features (≤3 for space)
    top_features = [(i["feature"], i["mean_drop"]) for i in expl.get("top", [])][:3]
    
    # Build HTML for PDF
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>ML Model Report: {_t(cfg.task.name)}</title>
    <style>
        @page {{
            size: A4 portrait;
            margin: 1.5cm;
        }}
        body {{
            font-family: system-ui, -apple-system, sans-serif;
            font-size: 11pt;
            line-height: 1.4;
            color: #1b1f24;
            max-width: 100%;
        }}
        h1 {{
            font-size: 16pt;
            margin: 0 0 8pt 0;
            padding-bottom: 4pt;
            border-bottom: 2px solid #0b5fff;
        }}
        h2 {{
            font-size: 13pt;
            margin: 12pt 0 6pt 0;
            color: #0b5fff;
        }}
        .metric-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8pt;
            margin: 8pt 0;
        }}
        .metric-box {{
            border: 1px solid #d0d7de;
            padding: 8pt;
            border-radius: 4pt;
        }}
        .metric-label {{
            font-size: 9pt;
            color: #59636e;
            text-transform: uppercase;
            letter-spacing: 0.5pt;
        }}
        .metric-value {{
            font-size: 14pt;
            font-weight: 600;
            margin-top: 2pt;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 8pt 0;
            font-size: 10pt;
        }}
        th, td {{
            text-align: left;
            padding: 4pt 8pt;
            border: 1px solid #d0d7de;
        }}
        th {{
            background: #f6f8fa;
            font-weight: 600;
        }}
        .finding {{
            margin: 4pt 0;
            padding: 4pt 8pt;
            background: #fff8e6;
            border-left: 3pt solid #ffa000;
            font-size: 10pt;
        }}
        .pass {{
            color: #0b5fff;
        }}
        .fail {{
            color: #b42318;
            font-weight: 600;
        }}
        .footer {{
            margin-top: 12pt;
            padding-top: 8pt;
            border-top: 1px solid #d0d7de;
            font-size: 9pt;
            color: #59636e;
        }}
    </style>
</head>
<body>
    <h1>ML Model Report: {_t(cfg.task.name)}</h1>
    
    <div class="metric-grid">
        <div class="metric-box">
            <div class="metric-label">Dataset Size</div>
            <div class="metric-value">{n_rows} rows × {n_cols} columns</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Model Performance</div>
            <div class="metric-value">{_format_metric(cfg.task.metric, val_score)}</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Model Family</div>
            <div class="metric-value">{_t(family)}</div>
        </div>
        <div class="metric-box">
            <div class="metric-label">Quality Checks</div>
            <div class="metric-value {'pass' if review.get('verdict') == 'APPROVE' else 'fail'}">
                {_t(str(review.get('verdict', 'n/a')))}
            </div>
        </div>
    </div>
    
    <h2>Data Quality</h2>
    <p>
        <strong>Leakage findings:</strong> {n_findings} total
        ({high_severity} high severity).
        {'All findings addressed.' if n_findings == 0 else 'See detailed report for remediation.'}
    </p>
    
    {_render_findings_table(findings[:5])}
    
    <h2>Model Comparison</h2>
    {_render_leaderboard_table(board[:5], cfg.task.metric)}
    
    {_render_feature_importance(top_features, cfg.task.metric) if top_features else ''}
    
    <h2>Intended Use</h2>
    <p>
        This model is designed for <strong>{cfg.task.task_type}</strong> prediction on
        tabular data similar to the training set. Performance on data from different
        distributions has not been validated. Validation scores shown are from a held-out
        subset and may be optimistic relative to real-world performance.
    </p>
    
    <div class="footer">
        Run ID: {_t(cfg.run_id)} | 
        Planner: {cfg.planner} | 
        Target: {_t(cfg.task.target)} | 
        Seed: {cfg.task.seed}
    </div>
</body>
</html>
"""
    
    # Generate PDF
    pdf_bytes = HTML(string=html_content).write_pdf()
    
    # Verify single-page constraint (PRD S21 acceptance)
    from pypdf import PdfReader  # type: ignore[import-untyped]
    
    reader = PdfReader(BytesIO(pdf_bytes))
    if len(reader.pages) != 1:
        raise ValueError(
            f"Generated PDF has {len(reader.pages)} pages, expected exactly 1 "
            "(PRD S21 acceptance criterion)"
        )
    
    # Write to file
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(pdf_bytes)


def _render_findings_table(findings: list[dict[str, Any]]) -> str:
    """Render leakage findings table (limited to top 5 for space)."""
    if not findings:
        return "<p><em>No leakage findings detected.</em></p>"
    
    rows = "\n".join(
        f"<tr><td>{_t(f['severity'])}</td><td>{_t(f['type'])}</td>"
        f"<td>{_t(', '.join(f['columns'][:3]), 80)}</td></tr>"
        for f in findings
    )
    return f"""<table>
        <tr><th>Severity</th><th>Type</th><th>Columns</th></tr>
        {rows}
    </table>"""


def _render_leaderboard_table(board: list[dict[str, Any]], metric: str) -> str:
    """Render model leaderboard (limited to top 5 for space)."""
    if not board:
        return "<p><em>No models trained.</em></p>"
    
    rows = "\n".join(
        f"<tr><td>{_t(m['model_id'], 30)}</td><td>{_t(m['family'])}</td>"
        f"<td>{m['val_score']:.4f}</td></tr>"
        for m in board
    )
    return f"""<table>
        <tr><th>Model</th><th>Family</th><th>{_t(metric)}</th></tr>
        {rows}
    </table>"""


def _render_feature_importance(features: list[tuple[str, float]], metric: str) -> str:
    """Render top 3 features by permutation importance."""
    rows = "\n".join(
        f"<tr><td>{_t(feat)}</td><td>{val:.4f}</td></tr>"
        for feat, val in features
    )
    return f"""<h2>Top Predictive Features</h2>
    <p><em>Permutation importance: score drop when feature is shuffled</em></p>
    <table>
        <tr><th>Feature</th><th>Importance ({_t(metric)} drop)</th></tr>
        {rows}
    </table>"""
