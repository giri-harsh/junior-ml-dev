"""Deterministic seeded splits. Train side is agent-visible; test labels go to scorer_data only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
from sklearn.model_selection import GroupShuffleSplit, train_test_split

from benchmarks.tasks.registry import TaskSpec

SEED = 20260101
TEST_SIZE = 0.2
ROW_ID = "row_id"


def frame_sha256(df: pd.DataFrame) -> str:
    """Content hash independent of parquet encoding: column names + per-row hashes."""
    h = hashlib.sha256()
    h.update("|".join(map(str, df.columns)).encode())
    h.update(pd.util.hash_pandas_object(df, index=True).to_numpy().tobytes())
    return h.hexdigest()


def make_split(
    df: pd.DataFrame, spec: TaskSpec, seed: int = SEED, test_size: float = TEST_SIZE
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (train, test) both carrying a stable `row_id` from the input position."""
    data = df.reset_index(drop=True).copy()
    data.insert(0, ROW_ID, range(len(data)))
    if spec.time_col:
        ordered = data.sort_values([spec.time_col, ROW_ID], kind="stable")
        cut = int(len(ordered) * (1 - test_size))
        return ordered.iloc[:cut].reset_index(drop=True), ordered.iloc[cut:].reset_index(drop=True)
    if spec.group_col:
        gss = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
        tr, te = next(gss.split(data, groups=data[spec.group_col]))
        return data.iloc[tr].reset_index(drop=True), data.iloc[te].reset_index(drop=True)
    stratify = data[spec.target] if spec.task_type != "regression" else None
    train, test = train_test_split(data, test_size=test_size, random_state=seed, stratify=stratify)
    return train.sort_values(ROW_ID).reset_index(drop=True), test.sort_values(ROW_ID).reset_index(
        drop=True
    )


def write_split(
    df: pd.DataFrame, spec: TaskSpec, agent_root: Path, scorer_root: Path
) -> dict[str, object]:
    train, test = make_split(df, spec)
    agent_dir = agent_root / spec.name
    scorer_dir = scorer_root / spec.name
    agent_dir.mkdir(parents=True, exist_ok=True)
    scorer_dir.mkdir(parents=True, exist_ok=True)
    features = test.drop(columns=[spec.target])
    labels = test[[ROW_ID, spec.target]]
    train.to_parquet(agent_dir / "train.parquet", index=False)
    features.to_parquet(scorer_dir / "test_features.parquet", index=False)
    labels.to_parquet(scorer_dir / "test_labels.parquet", index=False)
    manifest = {
        "task": spec.name,
        "seed": SEED,
        "test_size": TEST_SIZE,
        "n_train": len(train),
        "n_test": len(test),
        "train_sha256": frame_sha256(train),
        "test_features_sha256": frame_sha256(features),
    }
    (agent_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    scorer_manifest = {**manifest, "test_labels_sha256": frame_sha256(labels)}
    (scorer_dir / "manifest.json").write_text(json.dumps(scorer_manifest, indent=2, sort_keys=True))
    return manifest
