"""Threshold loading and hashing (the hash proves eval ran against the frozen file)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

THRESHOLDS_PATH = Path(__file__).with_name("thresholds.yaml")
FROZEN_HASH_PATH = Path(__file__).with_name("thresholds.frozen.sha256")


def thresholds_hash(path: Path = THRESHOLDS_PATH) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def assert_frozen() -> str:
    """Raise unless the thresholds file matches the committed frozen hash. Returns the hash."""
    if not FROZEN_HASH_PATH.exists():
        raise RuntimeError("thresholds not frozen: leakage/thresholds.frozen.sha256 missing")
    frozen = FROZEN_HASH_PATH.read_text().strip()
    current = thresholds_hash()
    if frozen != current:
        raise RuntimeError(f"thresholds changed after freeze: {current} != {frozen}")
    return current
