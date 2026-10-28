from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from apps.api.main import app
from harness.policies.actions import Action, RunContext, guard
from harness.security import auth
from harness.security.approvals import (
    AlreadyUsed,
    ApprovalStore,
    Expired,
    InvalidToken,
    Mismatch,
    payload_hash,
)
from harness.security.audit import GENESIS, AuditLog

PAYLOAD = {"model": "m1", "version": 3}


class Clock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def store(tmp_path: Path) -> tuple[ApprovalStore, Clock]:
    c = Clock()
    return ApprovalStore(tmp_path / "a.db", "unit-test-secret", clock=c), c


def _token(s: ApprovalStore) -> str:
    return s.approve(s.request("deploy", "run1", PAYLOAD))


def test_token_works_once_then_409(store: tuple[ApprovalStore, Clock]) -> None:
    s, _ = store
    tok = _token(s)
    s.consume(tok, "deploy", "run1", PAYLOAD)
    with pytest.raises(AlreadyUsed) as ei:
        s.consume(tok, "deploy", "run1", PAYLOAD)
    assert ei.value.http_status == 409


def test_token_is_bound_to_action_run_and_payload(store: tuple[ApprovalStore, Clock]) -> None:
    s, _ = store
    tok = _token(s)
    for args in (
        ("rollback", "run1", PAYLOAD),
        ("deploy", "run2", PAYLOAD),
        ("deploy", "run1", {"model": "evil"}),
    ):
        with pytest.raises(Mismatch):
            s.consume(tok, *args)
    s.consume(tok, "deploy", "run1", PAYLOAD)  # the failed attempts did not burn it


def test_expired_and_forged_tokens_are_rejected(store: tuple[ApprovalStore, Clock]) -> None:
    s, clock = store
    tok = _token(s)
    forged = tok[:-4] + "0000"
    with pytest.raises(InvalidToken):
        s.consume(forged, "deploy", "run1", PAYLOAD)
    with pytest.raises(InvalidToken):
        s.consume("garbage", "deploy", "run1", PAYLOAD)
    clock.t += 601
    with pytest.raises(Expired):
        s.consume(tok, "deploy", "run1", PAYLOAD)


def test_pending_request_cannot_be_used_and_cannot_be_approved_twice(
    store: tuple[ApprovalStore, Clock],
) -> None:
    s, _ = store
    aid = s.request("deploy", "run1", PAYLOAD)
    s.approve(aid)
    with pytest.raises(Exception, match="not pending"):
        s.approve(aid)


def test_concurrent_consumption_has_exactly_one_winner(tmp_path: Path) -> None:
    s = ApprovalStore(tmp_path / "race.db", "unit-test-secret")
    tok = s.approve(s.request("deploy", "run1", PAYLOAD))
    wins: list[int] = []

    def go() -> None:
        try:
            ApprovalStore(tmp_path / "race.db", "unit-test-secret").consume(
                tok, "deploy", "run1", PAYLOAD
            )
            wins.append(1)
        except (AlreadyUsed, sqlite3.OperationalError):
            pass

    threads = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(wins) == 1


def test_secret_is_mandatory(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ApprovalStore(tmp_path / "x.db", "")


def test_guard_deploy_uses_the_approval_validator(store: tuple[ApprovalStore, Clock]) -> None:
    s, _ = store
    tok = _token(s)
    ctx = RunContext(approval_validator=s.as_validator("run1", PAYLOAD))
    act = Action(type="deploy", approval_token=tok, payload_hash=payload_hash(PAYLOAD))
    assert guard(act, ctx).allowed
    s.consume(tok, "deploy", "run1", PAYLOAD)
    assert not guard(act, ctx).allowed  # replay after consumption is refused


# --- audit chain ------------------------------------------------------------------------------
def test_audit_chain_verifies_and_links(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.db", clock=lambda: "2026-01-01T00:00:00+00:00")
    h1 = log.append("admin", "login", {})
    log.append("agent", "tool_call", {"tool": "run_python", "code_hash": "abc"})
    es = log.entries()
    assert es[0]["prev_hash"] == GENESIS and es[1]["prev_hash"] == h1
    assert log.verify_chain() == (True, None)


def test_tampering_is_pinpointed_even_after_dropping_the_triggers(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.db")
    for i in range(5):
        log.append("a", "act", {"i": i})
    conn = sqlite3.connect(log.path)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):  # app role cannot edit
        conn.execute("UPDATE audit SET actor='x' WHERE id=3")
    conn.execute("DROP TRIGGER audit_no_update")  # a privileged attacker
    conn.execute("UPDATE audit SET payload='{\"i\":99}' WHERE id=3")
    conn.commit()
    conn.close()
    assert log.verify_chain() == (False, 3)


def test_deleting_or_reordering_rows_breaks_the_chain(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.db")
    for i in range(4):
        log.append("a", "act", {"i": i})
    conn = sqlite3.connect(log.path)
    conn.execute("DROP TRIGGER audit_no_delete")
    conn.execute("DELETE FROM audit WHERE id=2")
    conn.commit()
    conn.close()
    ok, bad = log.verify_chain()
    assert not ok and bad == 3


def test_concurrent_appends_keep_the_chain_valid(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.db")

    def go(n: int) -> None:
        for i in range(10):
            AuditLog(tmp_path / "audit.db").append(f"t{n}", "act", {"i": i})

    threads = [threading.Thread(target=go, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(log.entries()) == 40 and log.verify_chain() == (True, None)


@given(
    st.lists(
        st.dictionaries(st.text(max_size=6), st.integers() | st.text(max_size=8), max_size=4),
        max_size=12,
    )
)
@settings(max_examples=20, deadline=None)
def test_property_chain_verifies_for_random_sequences(payloads: list[dict[str, object]]) -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        log = AuditLog(Path(d) / "a.db")
        for p in payloads:
            log.append("actor", "act", p)
        assert log.verify_chain() == (True, None)


# --- admin API ----------------------------------------------------------------------------------
@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ADMIN_USER", "root")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", auth.hash_password("correct horse"))
    monkeypatch.setenv("JWT_SECRET", "jwt-unit-secret")
    monkeypatch.setenv("APPROVAL_SECRET", "approval-unit-secret")
    monkeypatch.setenv("AUDIT_DB", str(tmp_path / "audit.db"))
    monkeypatch.setenv("APPROVAL_DB", str(tmp_path / "approvals.db"))
    return TestClient(app)


def test_login_cookie_flags_and_failures(api: TestClient) -> None:
    bad = api.post("/v1/auth/login", json={"user": "root", "password": "wrong"})
    assert bad.status_code == 401
    ok = api.post("/v1/auth/login", json={"user": "root", "password": "correct horse"})
    assert ok.status_code == 200
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and auth.COOKIE in cookie
    assert (
        api.post("/v1/auth/login", json={"user": "nobody", "password": "correct horse"}).status_code
        == 401
    )


def test_login_disabled_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    r = TestClient(app).post("/v1/auth/login", json={"user": "root", "password": "x"})
    assert r.status_code == 503


def test_admin_endpoints_need_the_cookie(api: TestClient) -> None:
    assert api.get("/v1/audit").status_code == 401
    assert api.post("/v1/approvals/abc/approve").status_code == 401


def test_expired_session_is_rejected(api: TestClient) -> None:
    old = auth.issue_token("root", now=lambda: 1.0)  # issued in 1970, long expired
    api.cookies.set(auth.COOKIE, old)
    assert api.get("/v1/audit").status_code == 401
    api.cookies.set(auth.COOKIE, "not-a-jwt")
    assert api.get("/v1/audit").status_code == 401


def test_approval_flow_end_to_end_with_audit(api: TestClient, tmp_path: Path) -> None:
    api.post("/v1/auth/login", json={"user": "root", "password": "correct horse"})
    store = ApprovalStore(tmp_path / "approvals.db", "approval-unit-secret")
    aid = store.request("deploy", "run9", PAYLOAD)
    tok = api.post(f"/v1/approvals/{aid}/approve").json()["token"]
    store.consume(tok, "deploy", "run9", PAYLOAD)
    with pytest.raises(AlreadyUsed):
        store.consume(tok, "deploy", "run9", PAYLOAD)
    actions = [e["action"] for e in api.get("/v1/audit").json()]
    assert actions == ["login", "approval_granted"]
    assert api.get("/v1/audit/verify").json()["ok"] is True
    assert api.post(f"/v1/approvals/{aid}/approve").status_code == 400  # not pending any more
