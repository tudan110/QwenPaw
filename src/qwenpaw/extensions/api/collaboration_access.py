"""Short-lived, non-administrative leases for server-scheduled collaboration.

Only trusted server code issues leases. Job payload fields are never credentials.
The capability is restricted independently of the production guard setting.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import re
import secrets
import time

from fastapi import HTTPException

from .access_session import AccessIdentity, CURRENT_IDENTITY, get_access_store
from .inoe_settings_store import CURRENT_REQUEST_TOKEN

HEADER = "X-QwenPaw-Collaboration-Token"
ENV_KEY = "QWENPAW_REQUEST_COLLABORATION_TOKEN"
SOURCE = "cron_collaboration"
CURRENT_COLLABORATION_TOKEN: ContextVar[str] = ContextVar(
    "qwenpaw_collaboration_token", default=""
)
_MAX_TTL = 86400


def _table(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS collaboration_leases "
        "(token_hash TEXT PRIMARY KEY, job_id TEXT NOT NULL, "
        "expires_at REAL NOT NULL)"
    )


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_lease(job_id: str, timeout_seconds: int) -> str:
    """Issue a bounded capability; never exposed as an HTTP operation."""
    token = "qc1." + secrets.token_urlsafe(32)
    expires = time.time() + min(max(timeout_seconds + 30, 30), _MAX_TTL)
    with get_access_store()._connect() as conn:
        _table(conn)
        conn.execute(
            "DELETE FROM collaboration_leases WHERE expires_at <= ?",
            (time.time(),),
        )
        conn.execute(
            "INSERT INTO collaboration_leases VALUES (?, ?, ?)",
            (_hash(token), job_id, expires),
        )
    return token


def revoke_lease(token: str) -> None:
    with get_access_store()._connect() as conn:
        _table(conn)
        conn.execute(
            "DELETE FROM collaboration_leases WHERE token_hash=?",
            (_hash(token),),
        )


def resolve_lease(token: str, method: str, path: str) -> AccessIdentity:
    if not token.startswith("qc1.") or len(token) > 128:
        raise HTTPException(401, "协同任务凭据无效")
    with get_access_store()._connect() as conn:
        _table(conn)
        row = conn.execute(
            "SELECT job_id, expires_at FROM collaboration_leases "
            "WHERE token_hash=?",
            (_hash(token),),
        ).fetchone()
    if row is None or row["expires_at"] <= time.time():
        raise HTTPException(401, "协同任务凭据已撤销或过期")
    # Match exact paths: no generic GET, configuration, uploads or fork access.
    allowed = method == "GET" and path == "/api/agents"
    allowed |= method == "POST" and bool(
        re.fullmatch(r"/api/(?:agents/[^/]+/)?console/chat(?:/task)?", path)
    )
    allowed |= method == "GET" and bool(
        re.fullmatch(
            r"/api/(?:agents/[^/]+/)?console/chat/task/task-[a-f0-9]{12}",
            path,
        )
    )
    if not allowed:
        raise HTTPException(403, "协同任务凭据不允许访问此接口")
    # No INOE userId: can never acquire administrator privileges.
    return AccessIdentity(
        user={"service": SOURCE, "job_id": row["job_id"]},
        inoe_token="",
        source=SOURCE,
    )


@contextmanager
def scheduled_collaboration(
    job_id: str, timeout_seconds: int, *, force_service: bool = False
):
    """Bind one automatic run; manual runs retain their verified user."""
    if not force_service and CURRENT_IDENTITY.get() is not None:
        yield
        return
    lease = issue_lease(job_id, timeout_seconds)
    identity = resolve_lease(lease, "GET", "/api/agents")
    identity_ctx = CURRENT_IDENTITY.set(identity)
    inoe_ctx = CURRENT_REQUEST_TOKEN.set("")
    lease_ctx = CURRENT_COLLABORATION_TOKEN.set(lease)
    try:
        yield
    finally:
        CURRENT_COLLABORATION_TOKEN.reset(lease_ctx)
        CURRENT_REQUEST_TOKEN.reset(inoe_ctx)
        CURRENT_IDENTITY.reset(identity_ctx)
        revoke_lease(lease)
