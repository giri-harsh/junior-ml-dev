"""Pydantic schemas for profiling and the Data Story."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from leakage.models import Finding


class ColumnProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    dtype: str
    semantic_type: str  # numeric | categorical | boolean | datetime | text | id | constant
    missing_frac: float = Field(ge=0, le=1)
    n_unique: int
    near_constant: bool
    stats: dict[str, float] = Field(default_factory=dict)
    top_values: dict[str, float] = Field(default_factory=dict)
    target_association: float | None = None
    association_method: str | None = None
    roles: list[str] = Field(default_factory=list)  # id | time | group


class TargetProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    task_type: str
    n_classes: int | None = None
    class_balance: dict[str, float] = Field(default_factory=dict)
    majority_fraction: float | None = None
    imbalance_ratio: float | None = None
    skew: float | None = None
    missing_frac: float


class SampleInfo(BaseModel):
    n_full: int
    n_used: int
    sampled: bool
    seed: int


class DatasetProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_rows: int
    n_cols: int
    duplicate_rows: int
    target: TargetProfile | None
    columns: list[ColumnProfile]
    constant_columns: list[str]
    near_constant_columns: list[str]
    high_missing_columns: list[str]
    high_cardinality_columns: list[str]
    suspected_id: list[str]
    suspected_time: list[str]
    suspected_group: list[str]
    sample: SampleInfo | None = None


class StoryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: DatasetProfile
    findings: list[Finding]
    markdown: str
    meta: dict[str, Any] = Field(default_factory=dict)
    charts: dict[str, list[dict[str, Any]]] = Field(
        default_factory=dict,
        description="Vega-Lite chart specs (PRD S6) - keys: 'gallery' (top N), 'more_charts' (rest)",
    )
