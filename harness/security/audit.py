"""Hash-chained, append-only audit log (SQLite here; the same SQL shape works on Postgres).

hash_i = SHA256(prev_hash || canonical_json(record_i)). Appends are serialised with
BEGIN IMMEDIATE. Triggers block UPDATE/DELETE for the application connection; a privileged
tamper (dropping the triggers) is still detected by `verify_chain`. Tamper-evident, not
tamper-proof: anchor the head hash externally to detect a full rewrite.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


def canonical_json(obj: dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class AuditLog:
    def __init__(self, path: Path | str, clock: Callable[[], str] = _now) -> None:
        self.path = str(path)
        self.clock = clock
        with closing(self._conn()) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,"  # noqa: E501
                " actor TEXT NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL,"
                " prev_hash TEXT NOT NULL, hash TEXT NOT NULL)"
            )
            for op in ("UPDATE", "DELETE"):
                c.execute(
                    f"CREATE TRIGGER IF NOT EXISTS audit_no_{op.lower()} BEFORE {op} ON audit "
                    "BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END"
                )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def append(self, actor: str, action: str, payload: dict[str, Any]) -> str:
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")  # serialises concurrent appenders
            row = conn.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
            prev = row[0] if row else GENESIS
            record = {"ts": self.clock(), "actor": actor, "action": action, "payload": payload}
            digest = hashlib.sha256((prev + canonical_json(record)).encode()).hexdigest()
            conn.execute(
                "INSERT INTO audit (ts, actor, action, payload, prev_hash, hash) VALUES (?,?,?,?,?,?)",  # noqa: E501
                (record["ts"], actor, action, canonical_json(payload), prev, digest),
            )
            conn.execute("COMMIT")
            return digest
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def entries(self) -> list[dict[str, Any]]:
        with closing(self._conn()) as c:
            rows = c.execute(
                "SELECT id, ts, actor, action, payload, prev_hash, hash FROM audit ORDER BY id"
            ).fetchall()
        keys = ("id", "ts", "actor", "action", "payload", "prev_hash", "hash")
        return [dict(zip(keys, r, strict=True)) for r in rows]

    def verify_chain(self) -> tuple[bool, int | None]:
        """(ok, id of the first bad row). Detects edits, deletions, insertions and reordering."""
        prev = GENESIS
        for e in self.entries():
            record = {
                "ts": e["ts"],
                "actor": e["actor"],
                "action": e["action"],
                "payload": json.loads(e["payload"]),
            }
            expect = hashlib.sha256((prev + canonical_json(record)).encode()).hexdigest()
            if e["prev_hash"] != prev or e["hash"] != expect:
                return False, int(e["id"])
            prev = e["hash"]
        return True, None

    def head(self) -> str:
        es = self.entries()
        return es[-1]["hash"] if es else GENESIS
