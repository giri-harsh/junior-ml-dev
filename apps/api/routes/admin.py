"""Admin login, approvals and audit endpoints. Everything except login needs the admin cookie."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from harness.security import auth
from harness.security.approvals import ApprovalError, ApprovalStore
from harness.security.audit import AuditLog

router = APIRouter(prefix="/v1", tags=["admin"])


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: str = Field(max_length=128)
    password: str = Field(max_length=1024)


def audit_log() -> AuditLog:
    return AuditLog(os.environ.get("AUDIT_DB", "data/audit.db"))


def approval_store() -> ApprovalStore:
    secret = os.environ.get("APPROVAL_SECRET", "")
    if not secret:
        raise HTTPException(503, "APPROVAL_SECRET is not configured")
    return ApprovalStore(
        os.environ.get("APPROVAL_DB", "data/approvals.db"), secret, audit=audit_log()
    )


def require_admin(request: Request) -> str:
    token = request.cookies.get(auth.COOKIE)
    user = auth.read_token(token) if token else None
    if user is None:
        raise HTTPException(401, "admin login required")
    return user


@router.post("/auth/login")
def login(body: LoginBody, response: Response) -> dict[str, str]:
    try:
        ok = auth.verify_login(body.user, body.password)
    except auth.AuthDisabled:
        raise HTTPException(503, "admin login is not configured") from None
    if not ok:
        audit_log().append(body.user[:64], "login_failed", {})
        raise HTTPException(401, "invalid credentials")
    response.set_cookie(
        auth.COOKIE,
        auth.issue_token(body.user),
        httponly=True,
        samesite="strict",
        secure=os.environ.get("COOKIE_SECURE", "0") == "1",
        max_age=auth.TTL_SECONDS,
    )
    audit_log().append(body.user, "login", {})
    return {"status": "ok"}


@router.post("/auth/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(auth.COOKIE)
    return {"status": "ok"}


@router.post("/approvals/{approval_id}/approve")
def approve(approval_id: str, admin: str = Depends(require_admin)) -> dict[str, str]:
    store = approval_store()
    try:
        token = store.approve(approval_id)
    except ApprovalError as exc:
        raise HTTPException(exc.http_status, str(exc)) from None
    audit_log().append(admin, "approval_granted", {"approval_id": approval_id})
    return {"token": token}


@router.get("/audit")
def get_audit(admin: str = Depends(require_admin)) -> list[dict[str, Any]]:
    return audit_log().entries()


@router.get("/audit/verify")
def verify_audit(admin: str = Depends(require_admin)) -> dict[str, Any]:
    log = audit_log()
    ok, bad = log.verify_chain()
    return {"ok": ok, "first_bad_id": bad, "head": log.head()}
