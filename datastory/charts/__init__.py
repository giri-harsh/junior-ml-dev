"""Declarative chart generation (Vega-Lite via Altair) for data stories (PRD S6).

This module generates chart candidates alongside the existing inline-SVG approach in reports.
Charts are ranked by importance × clarity × novelty and rendered to SVG/PNG via vl-convert.
"""

from __future__ import annotations

from datastory.charts.models import ChartSpec
from datastory.charts.render import render_spec_to_svg
from datastory.charts.templates import generate_chart_candidates

__all__ = ["ChartSpec", "generate_chart_candidates", "render_spec_to_svg"]
