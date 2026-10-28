"""Finding schema and detection context shared by all detectors."""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    LOW = "low"  # advisory; never counts as a detection in evaluation
    MEDIUM = "medium"
    HIGH = "high"


class FindingType(StrEnum):
    TARGET_LEAKAGE = "target_leakage"
    POST_OUTCOME = "post_outcome"
    HIGH_CARDINALITY_PROXY = "high_cardinality_proxy"
    DUPLICATE_ROWS = "duplicate_rows"
    TEMPORAL_LEAKAGE = "temporal_leakage"
    GROUP_LEAKAGE = "group_leakage"
    TRAIN_TEST_CONTAMINATION = "train_test_contamination"
    ID_LEAK = "id_leak"
    ID_LIKE = "id_like"
    UNIT_MISMATCH = "unit_mismatch"
    SUSPICIOUS_COLUMN_NAME = "suspicious_column_name"


# finding type -> the planted `expected_detector` family it counts toward in evaluation
FAMILY: dict[FindingType, str] = {
    FindingType.TARGET_LEAKAGE: "target_proxy",
    FindingType.POST_OUTCOME: "target_proxy",
    FindingType.HIGH_CARDINALITY_PROXY: "target_proxy",
    FindingType.DUPLICATE_ROWS: "split_overlap",
    FindingType.TRAIN_TEST_CONTAMINATION: "split_overlap",
    FindingType.TEMPORAL_LEAKAGE: "temporal",
    FindingType.GROUP_LEAKAGE: "group",
    FindingType.ID_LEAK: "mi_spike",
    FindingType.ID_LIKE: "mi_spike",
    FindingType.UNIT_MISMATCH: "consistency",
    FindingType.SUSPICIOUS_COLUMN_NAME: "injection",
}


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: FindingType
    severity: Severity
    columns: list[str]
    evidence: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)

    @property
    def family(self) -> str:
        return FAMILY[self.type]


class DetectionMeta(BaseModel):
    """Everything a detector may know besides the frame. Never contains bug labels."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    task_type: str | None = None  # binary | multiclass | regression; inferred when None
    seed: int = 0
    max_cv_rows: int = 20_000
    holdout: pd.DataFrame | None = None  # optional second split for contamination checks
    time_budget_s: float = 120.0


class DetectionTimeout(RuntimeError):
    pass


class Budget:
    """Cooperative deadline; detectors call `check()` between expensive steps."""

    def __init__(self, seconds: float) -> None:
        self._end = time.monotonic() + seconds

    def check(self) -> None:
        if time.monotonic() >= self._end:
            raise DetectionTimeout("time budget exceeded")
