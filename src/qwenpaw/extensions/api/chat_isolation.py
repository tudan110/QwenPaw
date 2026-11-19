"""Server-owned namespaces for the trusted sample's Portal chat APIs."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from fastapi import HTTPException

from .access_session import CURRENT_IDENTITY
from ...constant import EnvVarLoader

_SESSION = re.compile(r"^qpsession1([0-9a-f]{32})([0-9a-f]{32})$")


@dataclass(frozen=True)
class PortalChatScope:
    digest: str

    @property
    def owner(self) -> str:
        return f"qpowner1{self.digest}"

    def session_id(self, value: str) -> str:
        if not isinstance(value, str) or not value or len(value) > 256:
            raise HTTPException(422, "会话标识无效")
        scoped = _SESSION.fullmatch(value)
        if scoped:
            if scoped[1] != self.digest:
                raise HTTPException(404, "会话不存在")
            return value
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
        return f"qpsession1{self.digest}{digest}"

    def owns(self, chat) -> bool:
        if chat is None or chat.user_id != self.owner or chat.channel != "console":
            return False
        scoped = _SESSION.fullmatch(chat.session_id)
        return scoped is not None and scoped[1] == self.digest


def chat_isolation_enabled() -> bool:
    """Read the protected sample setting for both API and storage gates."""
    return EnvVarLoader.get_str(
        "QWENPAW_TRUSTED_CHAT_ISOLATION", "false"
    ).strip().lower() in {"true", "1", "on", "yes"}


def chat_scope() -> PortalChatScope | None:
    """Require a verified Portal identity in the isolated sample profile."""
    if not chat_isolation_enabled():
        return None
    identity = CURRENT_IDENTITY.get()
    if identity is None or not identity.user_id or identity.source == "model_service":
        raise HTTPException(401, "请先通过智观认证")
    from .sso_settings_store import get_userinfo_url

    realm = get_userinfo_url()
    digest = hashlib.sha256(f"{realm}\0{identity.user_id}".encode("utf-8")).hexdigest()[:32]
    return PortalChatScope(digest)


def reject_reserved_legacy_namespace(owner: str, session_id: str) -> None:
    """Keep unauthenticated legacy clients out of isolated session files."""
    if str(owner).lower().startswith("qpowner1") or str(session_id).lower().startswith("qpsession1"):
        raise HTTPException(404, "会话不存在")


async def require_owned_chat(manager, chat_id: str, scope: PortalChatScope | None):
    chat = await manager.get_chat(chat_id)
    if not chat or (scope is not None and not scope.owns(chat)):
        raise HTTPException(404, "会话不存在")
    if scope is None:
        reject_reserved_legacy_namespace(chat.user_id, chat.session_id)
    return chat


def authorize_chat_payload(payload: dict, scope: PortalChatScope | None) -> None:
    """Use the same identity and namespaced ID in chat metadata and execution."""
    meta = payload["meta"]
    if scope is None:
        reject_reserved_legacy_namespace(payload["sender_id"], meta["session_id"])
        return
    if payload["channel_id"] != "console":
        raise HTTPException(422, "该入口仅支持 Portal 会话")
    payload["sender_id"] = scope.owner
    meta["user_id"] = scope.owner
    meta["session_id"] = scope.session_id(meta["session_id"])
    # Request context otherwise accepts keys consumed by the runtime, such
    # as project paths. Keep only the supported per-chat approval setting.
    request_context = meta.get("request_context")
    strict = isinstance(request_context, dict) and request_context.get("approval_level") == "strict"
    meta["request_context"] = {"approval_level": "strict" if strict else "smart"}
