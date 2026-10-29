"""Typed task registry loader."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

REGISTRY_PATH = Path(__file__).with_name("registry.yaml")
REGISTRY_V3_PATH = Path(__file__).with_name("registry_v3.yaml")
REGISTRY_V4_PATH = Path(__file__).with_name("registry_v4.yaml")
REGISTRY_V5_PATH = Path(__file__).with_name("registry_v5.yaml")

Metric = Literal["roc_auc", "pr_auc", "f1_macro", "rmse", "mae"]


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    source: Literal["openml"]
    task_type: Literal["binary", "multiclass", "regression"]
    target: str
    metric: Metric
    role: Literal["dev", "test", "p3_heldout", "v3_heldout", "v4_heldout", "v5_heldout"]
    imbalanced: bool = False
    group_col: str | None = None
    time_col: str | None = None

    @model_validator(mode="after")
    def _metric_fits_task(self) -> TaskSpec:
        reg = {"rmse", "mae"}
        if self.task_type == "regression" and self.metric not in reg:
            raise ValueError(f"{self.name}: regression needs rmse/mae")
        if self.task_type != "regression" and self.metric in reg:
            raise ValueError(f"{self.name}: classification cannot use {self.metric}")
        if self.task_type == "multiclass" and self.metric in {"roc_auc", "pr_auc"}:
            raise ValueError(f"{self.name}: multiclass supports f1_macro only")
        return self


def load_registry(path: Path = REGISTRY_PATH) -> list[TaskSpec]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    tasks = [TaskSpec.model_validate(t) for t in raw["tasks"]]
    names = [t.name for t in tasks]
    if len(set(names)) != len(names):
        raise ValueError("duplicate task names")
    return tasks


def load_registry_v3() -> list[TaskSpec]:
    """The v3 partition: never used for any design decision or earlier evaluation."""
    return load_registry(REGISTRY_V3_PATH)


def load_registry_v4() -> list[TaskSpec]:
    """The v4 partition (>= 2,000 test rows per task); unseen until its single evaluation."""
    return load_registry(REGISTRY_V4_PATH)


def load_registry_v5() -> list[TaskSpec]:
    """The v5 partition (run 6); unseen until its single evaluation."""
    return load_registry(REGISTRY_V5_PATH)


def partition(name: str) -> list[TaskSpec]:
    return {"v3": load_registry_v3, "v4": load_registry_v4, "v5": load_registry_v5}[name]()


def get_task(name: str) -> TaskSpec:
    """Looks in the original registry, then in v3 (the scorer resolves tasks through this)."""
    for t in [*load_registry(), *load_registry_v3(), *load_registry_v4(), *load_registry_v5()]:
        if t.name == name:
            return t
    raise KeyError(name)
