"""Single-use, payload-bound approval tokens for gated actions.

token = base64url(claims_json) + "." + HMAC_SHA256(secret, claims_json)
claims = {approval_id, action, run_id, payload_hash, exp}. Consumption is one atomic UPDATE
(`... WHERE used_at IS NULL AND expires_at > now`); exactly one caller can win a race.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
import uuid
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

TTL_SECONDS = 600


class ApprovalError(Exception):
    http_status = 400


class InvalidToken(ApprovalError):
    http_status = 401


class Expired(ApprovalError):
    http_status = 410


class AlreadyUsed(ApprovalError):
    http_status = 409


class Mismatch(ApprovalError):
    http_status = 403


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class ApprovalStore:
    def __init__(
        self,
        path: Path | str,
        secret: str,
        clock: Callable[[], float] | None = None,
        audit: Any | None = None,
    ) -> None:
        self.audit = audit  # optional AuditLog: consumption and rejection are recorded
        if not secret:
            raise ValueError("approval secret must be set (no default secret exists)")
        import time

        self.path, self.secret, self.clock = str(path), secret.encode(), clock or time.time
        with closing(self._conn()) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, action TEXT NOT NULL,"
                " run_id TEXT NOT NULL, payload_hash TEXT NOT NULL, status TEXT NOT NULL,"
                " expires_at REAL, used_at REAL)"
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30, isolation_level=None)

    def request(self, action: str, run_id: str, payload: dict[str, Any]) -> str:
        aid = uuid.uuid4().hex
        with closing(self._conn()) as c:
            c.execute(
                "INSERT INTO approvals (id, action, run_id, payload_hash, status) VALUES (?,?,?,?,?)",  # noqa: E501
                (aid, action, run_id, payload_hash(payload), "pending"),
            )
        return aid

    def approve(self, approval_id: str) -> str:
        """A human approves: marks the row, returns the signed token (shown once)."""
        exp = self.clock() + TTL_SECONDS
        with closing(self._conn()) as c:
            cur = c.execute(
                "UPDATE approvals SET status='approved', expires_at=? WHERE id=? AND status='pending'",  # noqa: E501
                (exp, approval_id),
            )
            if cur.rowcount != 1:
                raise ApprovalError("approval not pending")
            row = c.execute(
                "SELECT action, run_id, payload_hash FROM approvals WHERE id=?", (approval_id,)
            ).fetchone()
        claims = {
            "approval_id": approval_id, "action": row[0], "run_id": row[1],
            "payload_hash": row[2], "exp": exp,
        }  # fmt: skip
        body = json.dumps(claims, sort_keys=True).encode()
        sig = hmac.new(self.secret, body, hashlib.sha256).hexdigest()
        return f"{_b64(body)}.{sig}"

    def _claims(self, token: str) -> dict[str, Any]:
        try:
            body_b64, sig = token.split(".")
            body = _unb64(body_b64)
        except (ValueError, TypeError):
            raise InvalidToken("malformed token") from None
        good = hmac.new(self.secret, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good):
            raise InvalidToken("bad signature")
        claims = json.loads(body)
        assert isinstance(claims, dict)
        return claims

    def validate(self, token: str, action: str, run_id: str, payload: dict[str, Any]) -> None:
        """Check signature, binding and expiry WITHOUT consuming. Raises ApprovalError."""
        c = self._claims(token)
        if (
            c["action"] != action
            or c["run_id"] != run_id
            or c["payload_hash"] != payload_hash(payload)
        ):
            raise Mismatch("token is bound to a different action, run or payload")
        if self.clock() >= c["exp"]:
            raise Expired("token expired")
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT used_at FROM approvals WHERE id=?", (c["approval_id"],)
            ).fetchone()
        if row is None:
            raise InvalidToken("unknown approval")
        if row[0] is not None:
            raise AlreadyUsed("token already used")

    def consume(self, token: str, action: str, run_id: str, payload: dict[str, Any]) -> None:
        """Validate and atomically mark used. Exactly one concurrent caller succeeds."""
        try:
            self.validate(token, action, run_id, payload)
            c = self._claims(token)
            with closing(self._conn()) as conn:
                cur = conn.execute(
                    "UPDATE approvals SET used_at=? WHERE id=? AND used_at IS NULL"
                    " AND expires_at > ?",
                    (self.clock(), c["approval_id"], self.clock()),
                )
                if cur.rowcount != 1:
                    raise AlreadyUsed("token already used")
        except ApprovalError as exc:
            self._audit(
                "approval_rejected", run_id, {"action": action, "reason": type(exc).__name__}
            )
            raise
        self._audit(
            "approval_consumed", run_id, {"action": action, "approval_id": c["approval_id"]}
        )

    def _audit(self, what: str, run_id: str, payload: dict[str, Any]) -> None:
        if self.audit is not None:
            self.audit.append(f"approval:{run_id}", what, payload)

    def as_validator(self, run_id: str, payload: dict[str, Any]) -> Callable[[str, str, str], bool]:
        """Adapter for harness.policies.actions.RunContext.approval_validator (non-consuming)."""

        def check(token: str, action: str, _payload_hash: str) -> bool:
            try:
                self.validate(token, action, run_id, payload)
            except ApprovalError:
                return False
            return True

        return check
