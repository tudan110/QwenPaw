# -*- coding: utf-8 -*-
"""A separate capability credential for local model adapters, not INOE auth."""

from __future__ import annotations

import hmac
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException

from qwenpaw.security.secret_store import decrypt, encrypt, is_encrypted
from .access_session import get_access_store


def model_service_key(*, create: bool = False) -> str:
    store = get_access_store()
    with store._connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS internal_keys "
            "(name TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT value FROM internal_keys WHERE name='model_adapter'"
        ).fetchone()
        if row:
            value = decrypt(row["value"])
            if is_encrypted(value):
                raise HTTPException(503, "模型内部访问凭据不可解密")
            return value
        if not create:
            return ""
        value = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO internal_keys VALUES ('model_adapter', ?)",
            (encrypt(value),),
        )
        return value


def verify_model_service_key(value: str) -> bool:
    expected = model_service_key()
    return bool(
        expected and hmac.compare_digest(value.encode(), expected.encode())
    )


def local_model_headers(base_url: str) -> dict[str, str]:
    from qwenpaw.agents.tools.agent_management import (
        resolve_agent_api_base_url,
    )
    from .access_policy import is_model_adapter
    from qwenpaw.extensions.integrations.agent_api_auth import (
        is_trusted_api_target,
    )

    target = urlsplit(base_url)
    if not is_model_adapter(target.path.rstrip("/") + "/models"):
        return {}
    if not is_trusted_api_target(base_url, resolve_agent_api_base_url()):
        raise ValueError(
            "Local model adapter must use the trusted AI endpoint"
        )
    return {"X-QwenPaw-Model-Key": model_service_key(create=True)}
