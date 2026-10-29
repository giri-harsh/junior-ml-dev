"""Idempotency keys for run submission (SQLite).

A client that retries POST /v1/runs with the same `Idempotency-Key` and the same body gets the
original run back instead of a second run; the same key with a different body is a client bug and
is refused. The key is reserved BEFORE the work (unique constraint), so two concurrent requests
cannot both create a run: the loser sees `in_progress`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Literal

Outcome = Literal["new", "replay", "conflict", "in_progress"]


def body_hash(body: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


class IdempotencyStore:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS idem (key TEXT PRIMARY KEY, body_hash TEXT NOT NULL,"
                " response TEXT, created REAL NOT NULL)"
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30, isolation_level=None)

    def begin(self, key: str, bhash: str) -> tuple[Outcome, dict[str, Any] | None]:
        """Reserve `key`. 'new' = the caller does the work and must call `finish`."""
        with closing(self._conn()) as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO idem (key, body_hash, response, created)"
                " VALUES (?,?,NULL,?)",
                (key, bhash, time.time()),
            )
            if cur.rowcount == 1:
                return "new", None
            row = c.execute("SELECT body_hash, response FROM idem WHERE key=?", (key,)).fetchone()
        if row[0] != bhash:
            return "conflict", None
        if row[1] is None:
            return "in_progress", None
        return "replay", dict(json.loads(row[1]))

    def finish(self, key: str, response: dict[str, Any]) -> None:
        with closing(self._conn()) as c:
            c.execute("UPDATE idem SET response=? WHERE key=?", (json.dumps(response), key))

    def abandon(self, key: str) -> None:
        """The work failed before producing a response: free the key so the client can retry."""
        with closing(self._conn()) as c:
            c.execute("DELETE FROM idem WHERE key=? AND response IS NULL", (key,))
