# -*- coding: utf-8 -*-
"""SSO federation sessions with QwenPaw signing and distinct identities."""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import sqlite3
import secrets
import threading
import time
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from qwenpaw.constant import EnvVarLoader, SECRET_DIR
from qwenpaw.security.secret_store import decrypt, encrypt, is_encrypted

logger = logging.getLogger(__name__)

LOCAL_TOKEN_PREFIX = "qp1."
ACCESS_COOKIE = "qwenpaw_access_token"
ACCESS_TTL_SECONDS = 600


@dataclass(frozen=True)
class AccessIdentity:
    user: dict[str, Any]
    inoe_token: str = field(repr=False)
    access_token: str = field(default="", repr=False)
    source: str = "inoe"
    family_id: str = ""

    @property
    def user_id(self) -> str:
        value = self.user.get("userId")
        return str(value).strip() if value is not None else ""

    @property
    def is_admin(self) -> bool:
        allowed = {
            value.strip()
            for value in EnvVarLoader.get_str(
                "QWENPAW_ADMIN_INOE_USER_IDS", ""
            ).split(",")
            if value.strip()
        }
        return bool(self.user_id and self.user_id in allowed)


CURRENT_IDENTITY: contextvars.ContextVar[AccessIdentity | None] = (
    contextvars.ContextVar("qwenpaw_verified_identity", default=None)
)


def user_subject(user: dict[str, Any]) -> str:
    value = user.get("userId")
    if value is None or not str(value).strip():
        raise HTTPException(502, "智观认证响应缺少稳定用户 ID")
    return f"inoe:{str(value).strip()}"


def _session_subject(user: dict[str, Any]) -> str:
    from .sso_settings_store import get_userinfo_url

    realm = hashlib.sha256(get_userinfo_url().encode()).hexdigest()
    return f"{user_subject(user)}:{realm}"


class AccessSessionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or SECRET_DIR / "sso_access_sessions.db"
        self._initialized = False
        self._schema_lock = threading.Lock()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        with self._schema_lock:
            if not self._initialized:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("""CREATE TABLE IF NOT EXISTS access_sessions (
                token_hash TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                user_json TEXT NOT NULL,
                inoe_token TEXT NOT NULL,
                expires_at REAL NOT NULL,
                family_id TEXT NOT NULL
            )""")
                columns = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(access_sessions)"
                    )
                }
                if "family_id" not in columns:
                    conn.execute(
                        "ALTER TABLE access_sessions ADD COLUMN "
                        "family_id TEXT NOT NULL DEFAULT ''"
                    )
                    conn.execute(
                        "UPDATE access_sessions SET family_id=token_hash "
                        "WHERE family_id=''"
                    )
                conn.commit()
                self._initialized = True
        self.path.chmod(0o600)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def issue(
        self, inoe_token: str, user: dict[str, Any], *, family_id: str = ""
    ) -> dict[str, Any]:
        from qwenpaw.app import auth
        from qwenpaw.extensions.api.sso_auth import _cache_lifetime

        subject = _session_subject(user)
        ttl = int(_cache_lifetime(inoe_token, ACCESS_TTL_SECONDS))
        if ttl < 1:
            raise HTTPException(401, "智观登录凭据已过期，请重新登录")
        # Serialize first-key initialization across processes as well as
        # session writes. Signing material stays in the existing secret store.
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if family_id:
                parent = conn.execute(
                    "SELECT subject FROM access_sessions "
                    "WHERE family_id=? AND expires_at>? LIMIT 1",
                    (family_id, time.time()),
                ).fetchone()
                if parent is None or parent["subject"] != subject:
                    raise HTTPException(401, "登录会话已注销或失效，不能续期")
            data = auth._load_auth_data()
            if data.get("_auth_load_error") or is_encrypted(
                data.get("jwt_secret", "")
            ):
                raise HTTPException(503, "本地认证配置不可用")
            token = LOCAL_TOKEN_PREFIX + auth.create_token(subject, ttl)
            conn.execute(
                "INSERT INTO access_sessions VALUES (?, ?, ?, ?, ?, ?)",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    subject,
                    json.dumps(user, ensure_ascii=False),
                    encrypt(inoe_token),
                    time.time() + ttl,
                    family_id or secrets.token_urlsafe(16),
                ),
            )
            conn.execute(
                "DELETE FROM access_sessions WHERE expires_at <= ?",
                (time.time(),),
            )
        return {
            "access_token": token,
            "token_type": "Bearer",
            "token_kind": "qwenpaw",
            "expires_in_seconds": ttl,
            "user": user,
        }

    def resolve(self, token: str) -> AccessIdentity:
        from qwenpaw.app import auth

        if not token.startswith(LOCAL_TOKEN_PREFIX):
            raise HTTPException(401, "本地访问凭据格式无效")
        data = auth._load_auth_data()
        if (
            data.get("_auth_load_error")
            or not data.get("jwt_secret")
            or is_encrypted(data["jwt_secret"])
        ):
            raise HTTPException(503, "本地认证签名配置不可用")
        subject = auth.verify_token(token[len(LOCAL_TOKEN_PREFIX) :])
        if not subject:
            raise HTTPException(401, "本地访问凭据无效或已过期")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM access_sessions WHERE token_hash = ?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            ).fetchone()
        if not row or row["expires_at"] <= time.time():
            raise HTTPException(401, "本地登录会话无效或已过期")
        user = json.loads(row["user_json"])
        if not isinstance(user, dict):
            raise HTTPException(503, "本地登录身份记录损坏")
        if subject != row["subject"] or _session_subject(user) != subject:
            raise HTTPException(401, "本地登录身份不一致")
        inoe_token = decrypt(row["inoe_token"])
        if not inoe_token or is_encrypted(inoe_token):
            raise HTTPException(503, "智观业务凭据不可解密")
        return AccessIdentity(
            user=user,
            inoe_token=inoe_token,
            access_token=token,
            source="qwenpaw",
            family_id=row["family_id"],
        )

    def revoke(self, token: str) -> None:
        with self._connect() as conn:
            digest = hashlib.sha256(token.encode()).hexdigest()
            row = conn.execute(
                "SELECT family_id FROM access_sessions WHERE token_hash = ?",
                (digest,),
            ).fetchone()
            if row:
                conn.execute(
                    "DELETE FROM access_sessions WHERE family_id = ?",
                    (row["family_id"],),
                )


_STORE: AccessSessionStore | None = None


def get_access_store() -> AccessSessionStore:
    global _STORE
    if _STORE is None:
        _STORE = AccessSessionStore()
    return _STORE
