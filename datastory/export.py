"""HTML export for data story (PRD S7.5).

Self-contained HTML with embedded chart SVGs + spec JSON, no external dependencies.
"""
# ruff: noqa: E501

from __future__ import annotations

import html
import json
from typing import Any

from datastory.models import StoryResult


def _escape(text: str) -> str:
    """HTML-escape text."""
    return html.escape(str(text))


def _render_chart_section(charts_data: dict[str, list[dict[str, Any]]]) -> str:
    """Render charts as embedded SVGs with spec JSON."""
    if not charts_data:
        return ""

    gallery = charts_data.get("gallery", [])
    more_charts = charts_data.get("more_charts", [])

    sections = []

    if gallery:
        sections.append('<section class="chart-gallery">')
        sections.append("<h2>Chart Gallery</h2>")
        sections.append('<div class="charts-grid">')

        for chart in gallery:
            chart_id = _escape(chart.get("chart_id", "chart"))
            alt_text = _escape(chart.get("alt_text", "Chart"))
            spec = chart.get("spec", {})

            # Embed spec as JSON data attribute
            spec_json = json.dumps(spec, separators=(",", ":"))

            sections.append(f"<div class=\"chart-card\" data-spec='{spec_json}'>")
            sections.append(f'<p class="chart-alt">{alt_text}</p>')
            sections.append(
                f'<div class="chart-placeholder" id="{chart_id}">Chart: {alt_text}</div>'
            )  # noqa: E501
            sections.append("</div>")

        sections.append("</div>")
        sections.append("</section>")

    if more_charts:
        sections.append('<details class="more-charts">')
        sections.append("<summary>More Charts</summary>")
        sections.append('<div class="charts-grid">')

        for chart in more_charts:
            chart_id = _escape(chart.get("chart_id", "chart"))
            alt_text = _escape(chart.get("alt_text", "Chart"))
            spec = chart.get("spec", {})

            spec_json = json.dumps(spec, separators=(",", ":"))

            sections.append(f"<div class=\"chart-card\" data-spec='{spec_json}'>")
            sections.append(f'<p class="chart-alt">{alt_text}</p>')
            sections.append(
                f'<div class="chart-placeholder" id="{chart_id}">Chart: {alt_text}</div>'
            )  # noqa: E501
            sections.append("</div>")

        sections.append("</div>")
        sections.append("</details>")

    return "\n".join(sections)


def story_to_html(story: StoryResult, title: str = "Data Story") -> str:
    """Export data story as self-contained HTML (PRD S7.5).

    Embeds chart specs as JSON; placeholders for SVG rendering (would need vl-convert
    server-side or Vega-Lite JS client-side for actual rendering).

    Per PRD: self-contained, inline SVG + embedded spec JSON, no external scripts.
    """
    profile = story.profile

    # Basic profile info
    profile_section = f"""
<section class="profile-summary">
    <h2>Dataset Profile</h2>
    <ul>
        <li><strong>Rows:</strong> {profile.n_rows:,}</li>
        <li><strong>Columns:</strong> {profile.n_cols}</li>
        <li><strong>Duplicate rows:</strong> {profile.duplicate_rows:,}</li>
    </ul>
"""

    if profile.target:
        profile_section += f"""
    <div class="target-info">
        <h3>Target: {_escape(profile.target.name)}</h3>
        <p>Task type: {_escape(profile.target.task_type)}</p>
"""
        if profile.target.n_classes:
            profile_section += f"        <p>Classes: {profile.target.n_classes}</p>\n"
        if profile.target.majority_fraction:
            maj_frac = profile.target.majority_fraction
            profile_section += f"        <p>Majority fraction: {maj_frac:.1%}</p>\n"
        profile_section += "    </div>\n"

    profile_section += "</section>"

    # Findings section
    findings_section = ""
    if story.findings:
        findings_section = '<section class="findings">\n<h2>Leakage Findings</h2>\n<ul>\n'
        for finding in story.findings:
            severity = _escape(finding.severity.value.upper())
            finding_type = _escape(finding.type.value)
            columns = (
                ", ".join(_escape(c) for c in finding.columns)
                if finding.columns
                else "dataset-level"
            )  # noqa: E501
            findings_section += f"<li><strong>{severity}</strong>: {finding_type} on {columns} (confidence: {finding.confidence:.2f})</li>\n"  # noqa: E501
        findings_section += "</ul>\n</section>"

    # Markdown narrative
    narrative_section = f"""
<section class="narrative">
    <h2>Narrative</h2>
    <pre class="markdown-content">{_escape(story.markdown)}</pre>
</section>
"""

    # Charts section
    charts_section = _render_chart_section(story.charts)

    # Assemble HTML
    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{_escape(title)}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
            background: #f5f5f5;
        }}
        h1 {{ margin-bottom: 1.5rem; color: #1a1a1a; }}
        h2 {{ margin-top: 2rem; margin-bottom: 1rem; color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; }}  /* noqa */
        h3 {{ margin-top: 1.5rem; margin-bottom: 0.75rem; color: #34495e; }}
        section {{ background: white; padding: 1.5rem; margin-bottom: 1.5rem; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}  /* noqa */
        ul {{ margin-left: 1.5rem; }}
        li {{ margin-bottom: 0.5rem; }}
        .target-info {{ margin-top: 1rem; padding: 1rem; background: #ecf0f1; border-left: 4px solid #3498db; }}  /* noqa */
        .findings {{ background: #fff9e6; }}
        .findings strong {{ color: #e74c3c; }}
        .markdown-content {{ white-space: pre-wrap; font-family: 'Courier New', monospace; font-size: 0.9rem; background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto; }}  /* noqa */
        .chart-gallery, .more-charts {{ margin-top: 1rem; }}
        .charts-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 1.5rem; margin-top: 1rem; }}  /* noqa */
        .chart-card {{ background: #fafafa; border: 1px solid #ddd; border-radius: 4px; padding: 1rem; }}  /* noqa */
        .chart-alt {{ font-size: 0.9rem; color: #666; margin-bottom: 0.5rem; font-style: italic; }}
        .chart-placeholder {{ min-height: 300px; background: #e9ecef; border-radius: 4px; display: flex; align-items: center; justify-content: center; color: #6c757d; font-size: 0.9rem; }}  /* noqa */
        details summary {{ cursor: pointer; font-weight: bold; padding: 0.5rem; background: #f0f0f0; border-radius: 4px; }}  /* noqa */
        details summary:hover {{ background: #e0e0e0; }}
        details[open] {{ padding-bottom: 1rem; }}
    </style>
</head>
<body>
    <h1>{_escape(title)}</h1>
    
    {profile_section}
    
    {findings_section}
    
    {charts_section}
    
    {narrative_section}
    
    <footer style="text-align: center; color: #999; font-size: 0.85rem; margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #ddd;">  <!-- noqa -->
        Generated by junior-ml-dev data story export (PRD S7.5)
    </footer>
</body>
</html>
"""

    return html_doc
