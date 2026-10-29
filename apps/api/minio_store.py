"""MinIO/S3 object store behind the ObjectStore protocol. NOT RUN here (no MinIO).

Select with OBJECT_STORE=minio plus MINIO_ENDPOINT / MINIO_ROOT_USER / MINIO_ROOT_PASSWORD.
Verify with `pytest -m infra tests/infra/test_infra.py -k minio` after compose is up.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any

from apps.api.store import DATASET_ID


class MinioObjectStore:
    def __init__(self, client: Any | None = None, bucket: str = "jmd-datasets") -> None:
        if client is None:
            from minio import Minio

            client = Minio(
                os.environ.get("MINIO_ENDPOINT", "localhost:9000"),
                access_key=os.environ["MINIO_ROOT_USER"],
                secret_key=os.environ["MINIO_ROOT_PASSWORD"],
                secure=os.environ.get("MINIO_SECURE", "0") == "1",
            )
        self.client, self.bucket = client, bucket
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

    def _key(self, dataset_id: str, name: str) -> str:
        if not DATASET_ID.match(dataset_id):
            raise ValueError("invalid dataset id")
        if "/" in name or "\\" in name or name.startswith("."):
            raise ValueError("invalid object name")
        return f"{dataset_id}/{name}"

    def put_blob(self, dataset_id: str, name: str, data: bytes) -> None:
        self.client.put_object(
            self.bucket, self._key(dataset_id, name), io.BytesIO(data), len(data)
        )

    def get_blob(self, dataset_id: str, name: str) -> bytes | None:
        try:
            resp = self.client.get_object(self.bucket, self._key(dataset_id, name))
        except Exception as exc:  # minio.error.S3Error NoSuchKey; avoid importing minio here
            if getattr(exc, "code", "") in {"NoSuchKey", "NoSuchObject"}:
                return None
            raise
        try:
            return bytes(resp.read())
        finally:
            resp.close()
            resp.release_conn()

    def put_json(self, dataset_id: str, name: str, obj: dict[str, Any]) -> None:
        self.put_blob(dataset_id, name, json.dumps(obj, sort_keys=True).encode())

    def get_json(self, dataset_id: str, name: str) -> dict[str, Any] | None:
        raw = self.get_blob(dataset_id, name)
        return None if raw is None else dict(json.loads(raw))

    def exists(self, dataset_id: str) -> bool:
        self._key(dataset_id, "x")
        return any(True for _ in self.client.list_objects(self.bucket, prefix=f"{dataset_id}/"))

    def path_of(self, dataset_id: str, name: str) -> Path:
        raise NotImplementedError("object-store blobs have no local path; use get_blob")
