"""Chart templates (Altair/Vega-Lite) for PRD S6.1-S6.2.

Templates: histogram+density, top-k+other bar, target balance, box-by-class, rate-by-category with
CI bars, clustered heatmap, missingness matrix, time trend, MI bar, 2-D PCA scatter. Server-side
aggregation/sampling (≤5k points/chart).
"""

from __future__ import annotations

import contextlib
from typing import Any

import altair as alt
import numpy as np
import pandas as pd
from scipy.cluster import hierarchy  # type: ignore[import-untyped]

from datastory.charts.models import ChartSpec

MAX_POINTS = 5000


def _sample(df: pd.DataFrame, n: int = MAX_POINTS) -> pd.DataFrame:
    """Server-side sampling (PRD S6.2: ≤5k points/chart)."""
    if len(df) <= n:
        return df
    return df.sample(n=n, random_state=42).reset_index(drop=True)


def histogram_with_density(df: pd.DataFrame, col: str, insight_id: str | None = None) -> ChartSpec:
    """Histogram + density overlay (PRD S6.1)."""
    df_plot = _sample(df[[col]].dropna())
    chart = (
        alt.Chart(df_plot)
        .mark_bar(opacity=0.5)
        .encode(
            x=alt.X(f"{col}:Q", bin=alt.Bin(maxbins=30), title=col),
            y=alt.Y("count():Q", title="Count"),
        )
    )
    density = (
        alt.Chart(df_plot)
        .transform_density(col, as_=[col, "density"])
        .mark_line(color="red")
        .encode(x=f"{col}:Q", y=alt.Y("density:Q", title="Density"))
    )
    # fmt: skip
    spec = (
        (chart + density)
        .properties(width=400, height=250, title=f"Distribution of {col}")
        .to_dict()
    )
    return ChartSpec(
        chart_id=f"hist_{col}",
        spec=spec,
        alt_text=f"Histogram and density plot of {col}",
        insight_id=insight_id,
        template="histogram_density",
        columns=[col],
    )


def top_k_bar(df: pd.DataFrame, col: str, k: int = 10, insight_id: str | None = None) -> ChartSpec:
    """Top-k categories + 'Other' bar chart (PRD S6.1)."""
    counts = df[col].value_counts()
    top = counts.head(k)
    other = counts[k:].sum() if len(counts) > k else 0
    data = pd.DataFrame({"category": list(top.index) + (["Other"] if other > 0 else []),
                         "count": list(top.values) + ([other] if other > 0 else [])})  # fmt: skip
    chart = (
        alt.Chart(data)
        .mark_bar()
        .encode(
            y=alt.Y("category:N", sort="-x", title=col),
            x=alt.X("count:Q", title="Count"),
            tooltip=["category:N", "count:Q"],
        )
        .properties(width=400, height=min(22 * len(data), 300), title=f"Top {k} values: {col}")
    )
    spec = chart.to_dict()
    return ChartSpec(
        chart_id=f"topk_{col}",
        spec=spec,
        alt_text=f"Bar chart of top {k} categories in {col}",
        insight_id=insight_id,
        template="top_k_bar",
        columns=[col],
    )


def target_balance(df: pd.DataFrame, target: str, insight_id: str | None = None) -> ChartSpec:
    """Target class balance bar (PRD S6.1)."""
    counts = df[target].value_counts().reset_index()
    counts.columns = ["value", "count"]
    chart = (
        alt.Chart(counts)
        .mark_bar()
        .encode(
            x=alt.X("value:N", title=target),
            y=alt.Y("count:Q", title="Count"),
            tooltip=["value:N", "count:Q"],
        )
        .properties(width=400, height=250, title=f"Target balance: {target}")
    )
    spec = chart.to_dict()
    return ChartSpec(
        chart_id=f"balance_{target}",
        spec=spec,
        alt_text=f"Class balance of target {target}",
        insight_id=insight_id,
        template="target_balance",
        columns=[target],
    )


def box_by_class(
    df: pd.DataFrame, feature: str, target: str, insight_id: str | None = None
) -> ChartSpec:
    """Box plot by class + density strip (PRD S6.1)."""
    df_plot = _sample(df[[feature, target]].dropna())
    box = (
        alt.Chart(df_plot)
        .mark_boxplot()
        .encode(
            x=alt.X(f"{target}:N", title=target),
            y=alt.Y(f"{feature}:Q", title=feature),
        )
    )
    strip = (
        alt.Chart(df_plot)
        .mark_tick(opacity=0.2, thickness=1)
        .encode(x=f"{target}:N", y=f"{feature}:Q")
    )
    spec = (box + strip).properties(
        width=400, height=250, title=f"{feature} by {target}"
    ).to_dict()  # fmt: skip
    return ChartSpec(
        chart_id=f"box_{feature}_{target}",
        spec=spec,
        alt_text=f"Box plot and density strip of {feature} by {target}",
        insight_id=insight_id,
        template="box_by_class",
        columns=[feature, target],
    )


def rate_by_category(
    df: pd.DataFrame, cat_col: str, target: str, insight_id: str | None = None
) -> ChartSpec:
    """Rate by category with Wilson CI error bars (PRD S6.1)."""
    from leakage.evaluate import wilson

    grouped = df.groupby(cat_col)[target].agg(["sum", "count"]).reset_index()
    grouped.columns = ["category", "pos", "total"]
    grouped["rate"] = grouped["pos"] / grouped["total"]
    cis = [wilson(int(r["pos"]), int(r["total"])) for _, r in grouped.iterrows()]
    grouped["ci_low"], grouped["ci_high"] = zip(*cis, strict=True)
    grouped["error_low"] = grouped["rate"] - grouped["ci_low"]
    grouped["error_high"] = grouped["ci_high"] - grouped["rate"]

    chart = (
        alt.Chart(grouped)
        .mark_point()
        .encode(
            y=alt.Y("category:N", sort="-x", title=cat_col),
            x=alt.X("rate:Q", title="Positive rate", scale=alt.Scale(domain=[0, 1])),
            tooltip=["category:N", "rate:Q", "total:Q"],
        )
    )
    error = chart.mark_errorbar().encode(
        x=alt.X("ci_low:Q"),
        x2="ci_high:Q",
        y=alt.Y("category:N"),
    )
    spec = (chart + error).properties(
        width=400, height=min(22 * len(grouped), 350), title=f"Rate by {cat_col}"
    ).to_dict()  # fmt: skip
    return ChartSpec(
        chart_id=f"rate_{cat_col}_{target}",
        spec=spec,
        alt_text=f"Positive rate of {target} by {cat_col} with 95% Wilson CI",
        insight_id=insight_id,
        template="rate_by_category",
        columns=[cat_col, target],
    )


def clustered_heatmap(
    df: pd.DataFrame, features: list[str], insight_id: str | None = None
) -> ChartSpec:
    """Clustered correlation heatmap (PRD S6.1: via scipy.cluster.hierarchy)."""
    df_num = df[features].select_dtypes(include=[np.number]).dropna()
    if len(df_num.columns) < 2:
        # Fallback: return a simple correlation matrix without clustering
        corr = df_num.corr()
        data = corr.reset_index().melt(id_vars="index")
        data.columns = ["var1", "var2", "correlation"]
        chart = (
            alt.Chart(data)
            .mark_rect()
            .encode(
                x=alt.X("var1:N", title=""),
                y=alt.Y("var2:N", title=""),
                color=alt.Color("correlation:Q", scale=alt.Scale(scheme="redblue", domain=[-1, 1])),
                tooltip=["var1:N", "var2:N", "correlation:Q"],
            )
            .properties(width=400, height=400, title="Correlation matrix")
        )
        spec = chart.to_dict()
        return ChartSpec(
            chart_id="heatmap_corr",
            spec=spec,
            alt_text="Correlation heatmap of numeric features",
            insight_id=insight_id,
            template="clustered_heatmap",
            columns=list(df_num.columns),
        )

    corr = df_num.corr()
    linkage = hierarchy.linkage(corr, method="average")
    dendro = hierarchy.dendrogram(linkage, no_plot=True)
    order = dendro["leaves"]
    corr_ordered = corr.iloc[order, order]

    data = corr_ordered.reset_index().melt(id_vars="index")
    data.columns = ["var1", "var2", "correlation"]
    chart = (
        alt.Chart(data)
        .mark_rect()
        .encode(
            x=alt.X("var1:N", title="", sort=None),
            y=alt.Y("var2:N", title="", sort=None),
            color=alt.Color("correlation:Q", scale=alt.Scale(scheme="redblue", domain=[-1, 1])),
            tooltip=["var1:N", "var2:N", "correlation:Q"],
        )
        .properties(width=400, height=400, title="Clustered correlation heatmap")
    )
    spec = chart.to_dict()
    return ChartSpec(
        chart_id="heatmap_clustered",
        spec=spec,
        alt_text="Clustered correlation heatmap of numeric features",
        insight_id=insight_id,
        template="clustered_heatmap",
        columns=list(df_num.columns),
    )


def missingness_matrix(df: pd.DataFrame, insight_id: str | None = None) -> ChartSpec:
    """Missingness matrix (PRD S6.1)."""
    missing = df.isnull()
    sample_rows = min(len(df), 200)
    missing_sample = missing.head(sample_rows).reset_index(drop=True)
    data = []
    for col in missing_sample.columns:
        for idx in range(len(missing_sample)):
            if missing_sample.loc[idx, col]:
                data.append({"row": idx, "column": col})
    if not data:
        # No missing data: create empty chart
        chart = (
            alt.Chart(pd.DataFrame({"x": [0]}))
            .mark_text(text="No missing data")
            .properties(width=400, height=100)
        )
        spec = chart.to_dict()
        return ChartSpec(
            chart_id="missing_matrix",
            spec=spec,
            alt_text="Missingness matrix (no missing data)",
            insight_id=insight_id,
            template="missingness_matrix",
            columns=list(df.columns),
        )

    chart_data = pd.DataFrame(data)
    chart = (
        alt.Chart(chart_data)
        .mark_rect()
        .encode(
            x=alt.X("column:N", title="Column"),
            y=alt.Y("row:Q", title=f"Row (first {sample_rows})"),
            color=alt.value("red"),
            tooltip=["column:N", "row:Q"],
        )
        .properties(width=400, height=250, title="Missingness pattern")
    )
    spec = chart.to_dict()
    return ChartSpec(
        chart_id="missing_matrix",
        spec=spec,
        alt_text=f"Missingness matrix showing missing values across first {sample_rows} rows",
        insight_id=insight_id,
        template="missingness_matrix",
        columns=list(df.columns),
    )


def mi_bar(mi_scores: dict[str, float], insight_id: str | None = None) -> ChartSpec:
    """Mutual information bar chart (PRD S6.1)."""
    data = pd.DataFrame({"feature": list(mi_scores.keys()), "MI": list(mi_scores.values())})
    data = data.sort_values("MI", ascending=False).head(15)
    chart = (
        alt.Chart(data)
        .mark_bar()
        .encode(
            y=alt.Y("feature:N", sort="-x", title="Feature"),
            x=alt.X("MI:Q", title="Mutual Information"),
            tooltip=["feature:N", "MI:Q"],
        )
        .properties(width=400, height=min(22 * len(data), 350), title="Feature importance (MI)")
    )
    spec = chart.to_dict()
    return ChartSpec(
        chart_id="mi_scores",
        spec=spec,
        alt_text="Bar chart of mutual information scores for top features",
        insight_id=insight_id,
        template="mi_bar",
        columns=list(mi_scores.keys()),
    )


def time_trend(
    df: pd.DataFrame, time_col: str, value_col: str, insight_id: str | None = None
) -> ChartSpec:
    """Time trend + rolling mean (PRD S6.1)."""
    df_plot = _sample(df[[time_col, value_col]].dropna().sort_values(time_col))
    # fmt: skip
    window = min(20, len(df_plot) // 10)
    df_plot["rolling"] = df_plot[value_col].rolling(window=window, min_periods=1).mean()

    line = (
        alt.Chart(df_plot)
        .mark_line(opacity=0.3)
        .encode(
            x=alt.X(f"{time_col}:T", title=time_col),
            y=alt.Y(f"{value_col}:Q", title=value_col),
        )
    )
    rolling = (
        alt.Chart(df_plot)
        .mark_line(color="red")
        .encode(
            x=alt.X(f"{time_col}:T"),
            y=alt.Y("rolling:Q"),
        )
    )
    spec = (line + rolling).properties(
        width=400, height=250, title=f"Time trend: {value_col}"
    ).to_dict()  # fmt: skip
    return ChartSpec(
        chart_id=f"time_{time_col}_{value_col}",
        spec=spec,
        alt_text=f"Time trend of {value_col} over {time_col} with rolling mean",
        insight_id=insight_id,
        template="time_trend",
        columns=[time_col, value_col],
    )


def generate_chart_candidates(
    df: pd.DataFrame,
    target: str,
    insights: list[dict[str, Any]],
    profile: dict[str, Any],
) -> list[ChartSpec]:
    """Generate chart candidates mapped to insights (PRD S6.2).

    Returns unranked candidates; ranking happens in ranking.py.
    """
    charts: list[ChartSpec] = []
    cols = profile.get("columns", [])
    numeric_cols = [c["name"] for c in cols if c.get("semantic_type") in ("numeric", "id")]
    categorical_cols = [c["name"] for c in cols if c.get("semantic_type") == "categorical"]
    time_cols = [c["name"] for c in cols if c.get("semantic_type") == "datetime"]

    # Target balance
    if target in df.columns:
        charts.append(target_balance(df, target))

    # Histogram for top numeric features
    for col in numeric_cols[:5]:
        if col != target and col in df.columns:
            charts.append(histogram_with_density(df, col))

    # Top-k bars for categorical
    for col in categorical_cols[:3]:
        if col in df.columns:
            charts.append(top_k_bar(df, col, k=10))

    # Box plots for numeric vs target
    if target in df.columns and df[target].dtype in (int, float, "Int64", "Float64"):
        # Regression target: skip box-by-class
        pass
    else:
        for col in numeric_cols[:3]:
            if col != target and col in df.columns and target in df.columns:
                with contextlib.suppress(Exception):
                    charts.append(box_by_class(df, col, target))

    # MI bar if available
    mi_insight = next((i for i in insights if i.get("type") == "mutual_information"), None)
    if mi_insight and mi_insight.get("facts", {}).get("mi_scores"):
        charts.append(mi_bar(mi_insight["facts"]["mi_scores"]))

    # Missingness matrix
    if df.isnull().any().any():
        charts.append(missingness_matrix(df))

    # Time trend if time column exists
    if time_cols and numeric_cols:
        time_col = time_cols[0]
        value_col = numeric_cols[0]
        if time_col in df.columns and value_col in df.columns:
            with contextlib.suppress(Exception):
                charts.append(time_trend(df, time_col, value_col))

    # Clustered heatmap for correlations
    if len(numeric_cols) >= 3:
        with contextlib.suppress(Exception):
            charts.append(clustered_heatmap(df, numeric_cols[:10]))

    return charts
