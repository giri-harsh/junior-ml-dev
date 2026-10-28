"""Typed task registry loader."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

REGISTRY_PATH = Path(__file__).with_name("registry.yaml")

Metric = Literal["roc_auc", "pr_auc", "f1_macro", "rmse", "mae"]


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    source: Literal["openml"]
    task_type: Literal["binary", "multiclass", "regression"]
    target: str
    metric: Metric
    role: Literal["dev", "test", "p3_heldout"]
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


def get_task(name: str) -> TaskSpec:
    for t in load_registry():
        if t.name == name:
            return t
    raise KeyError(name)
