"""Object store interface. Local filesystem implementation; MinIO/S3 is a documented STUB."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Protocol

DATASET_ID = re.compile(r"^[0-9a-f]{16}$")


class ObjectStore(Protocol):
    def put_blob(self, dataset_id: str, name: str, data: bytes) -> None: ...
    def get_blob(self, dataset_id: str, name: str) -> bytes | None: ...
    def put_json(self, dataset_id: str, name: str, obj: dict[str, Any]) -> None: ...
    def get_json(self, dataset_id: str, name: str) -> dict[str, Any] | None: ...
    def exists(self, dataset_id: str) -> bool: ...
    def path_of(self, dataset_id: str, name: str) -> Path: ...


class LocalObjectStore:
    """Datasets are versioned by content hash: dataset_id = sha256(bytes)[:16]."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(os.environ.get("DATA_STORE_DIR", "data/store"))

    def _dir(self, dataset_id: str) -> Path:
        if not DATASET_ID.match(dataset_id):
            raise ValueError("invalid dataset id")
        return self.root / dataset_id

    def path_of(self, dataset_id: str, name: str) -> Path:
        if "/" in name or "\\" in name or name.startswith("."):
            raise ValueError("invalid object name")
        return self._dir(dataset_id) / name

    def put_blob(self, dataset_id: str, name: str, data: bytes) -> None:
        p = self.path_of(dataset_id, name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get_blob(self, dataset_id: str, name: str) -> bytes | None:
        p = self.path_of(dataset_id, name)
        return p.read_bytes() if p.exists() else None

    def put_json(self, dataset_id: str, name: str, obj: dict[str, Any]) -> None:
        self.put_blob(dataset_id, name, json.dumps(obj, sort_keys=True).encode())

    def get_json(self, dataset_id: str, name: str) -> dict[str, Any] | None:
        raw = self.get_blob(dataset_id, name)
        if raw is None:
            return None
        loaded = json.loads(raw)
        assert isinstance(loaded, dict)
        return loaded

    def exists(self, dataset_id: str) -> bool:
        return self._dir(dataset_id).is_dir()
