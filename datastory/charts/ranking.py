"""Chart ranking (PRD S6.3): importance × clarity × novelty penalty.

Top 8–12 to gallery, rest "More charts". Novelty penalty uses column-set Jaccard similarity.
"""

from __future__ import annotations

from typing import Any

from datastory.charts.models import ChartSpec


def _jaccard(set1: set[str], set2: set[str]) -> float:
    """Jaccard similarity between two sets."""
    if not set1 and not set2:
        return 1.0
    if not set1 or not set2:
        return 0.0
    return len(set1 & set2) / len(set1 | set2)


def _novelty_penalty(chart: ChartSpec, prev_charts: list[ChartSpec]) -> float:
    """Novelty penalty (PRD S6.3): 1.0 if unique columns, lower if overlap with previous."""
    if not prev_charts:
        return 1.0
    chart_cols = set(chart.columns)
    max_overlap = max(_jaccard(chart_cols, set(c.columns)) for c in prev_charts)
    return 1.0 - max_overlap


def rank_charts(
    charts: list[ChartSpec],
    insights: list[dict[str, Any]],
    top_n: int = 12,
) -> tuple[list[ChartSpec], list[ChartSpec]]:
    """Rank charts and split into gallery (top N) and 'More charts' (PRD S6.3).

    Ranking = insight importance × clarity prior × novelty penalty.

    Clarity priors (template-specific, hand-tuned):
    - histogram_density: 0.9 (clear, common)
    - top_k_bar: 0.9
    - target_balance: 1.0 (always important)
    - box_by_class: 0.8
    - rate_by_category: 0.7 (requires understanding CIs)
    - clustered_heatmap: 0.6 (dense)
    - missingness_matrix: 0.7
    - time_trend: 0.8
    - mi_bar: 0.95 (high signal)

    Returns (gallery, more_charts).
    """
    clarity_priors = {
        "histogram_density": 0.9,
        "top_k_bar": 0.9,
        "target_balance": 1.0,
        "box_by_class": 0.8,
        "rate_by_category": 0.7,
        "clustered_heatmap": 0.6,
        "missingness_matrix": 0.7,
        "time_trend": 0.8,
        "mi_bar": 0.95,
    }

    # Map insights by ID for fast lookup
    insight_map = {i.get("id", ""): i for i in insights}

    # Score each chart
    scored: list[tuple[float, ChartSpec]] = []
    selected: list[ChartSpec] = []

    for chart in charts:
        # Importance from insight if mapped
        importance = 1.0
        if chart.insight_id and chart.insight_id in insight_map:
            importance = insight_map[chart.insight_id].get("importance", 1.0)

        clarity = clarity_priors.get(chart.template, 0.5)
        novelty = _novelty_penalty(chart, selected)
        score = importance * clarity * novelty
        chart.importance_score = score
        scored.append((score, chart))
        selected.append(chart)

    # Sort by score descending
    scored.sort(key=lambda x: -x[0])

    # Deduplicate by column set (PRD S6 acceptance)
    # No two gallery charts share identical column set
    seen_cols: set[frozenset[str]] = set()
    gallery: list[ChartSpec] = []
    more: list[ChartSpec] = []

    for _score, chart in scored:
        col_set = frozenset(chart.columns)
        if col_set not in seen_cols and len(gallery) < top_n:
            chart.rank = len(gallery) + 1
            gallery.append(chart)
            seen_cols.add(col_set)
        else:
            more.append(chart)

    return gallery, more
