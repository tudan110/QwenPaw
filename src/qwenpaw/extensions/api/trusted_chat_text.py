"""Optional text-only admission rules for the independently configured Portal sample."""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import unicodedata

from fastapi import HTTPException

from ..security.execution_policy import enabled as production_guards
from .access_session import CURRENT_IDENTITY
from .collaboration_access import SOURCE as SCHEDULED_SOURCE
from .controlled_documents import Actor, transaction, Rejected
from .sso_settings_store import get_userinfo_url

logger = logging.getLogger(__name__)

RULES = (
    ("role-override", re.compile(r"(?im)^\s*(?:忽略|无视|覆盖)\s*(?:之前|先前|以上|全部|所有)?\s*(?:的)?\s*(?:系统|开发者|安全)(?:提示词|指令|规则)|^\s*(?:ignore|override)\s+(?:all\s+)?(?:previous\s+)?(?:system|developer|security)\s+(?:instructions|rules|prompts?)")),
    ("identity-spoof", re.compile(r"(?im)^\s*(?:假装|伪装成|冒充)\s*(?:AI\s*)?(?:管理员|系统用户)\s*(?:[,，。:]|来|并|，)?\s*(?:执行|调用|访问|导出|绕过)|^\s*(?:pretend|act)\s+(?:to be|as)\s+(?:an?\s+)?(?:administrator|system user)\s+(?:and|to)\s+(?:run|invoke|access|export|bypass)")),
    ("secret-extraction", re.compile(r"(?im)^\s*(?:请\s*)?(?:输出|打印|透露|展示|发给我|返回)\s*(?:完整|全部|所有|你的)?\s*(?:的)?\s*(?:系统提示词|开发者提示词|完整环境变量|未脱敏的(?:系统密钥|访问令牌))|^\s*(?:print|reveal|expose|dump)\s+(?:the\s+|your\s+)?(?:full\s+)?(?:system prompt|developer prompt|environment variables|unmasked secrets)")),
)

MAX_INPUT = 32_000


def enabled() -> bool:
    from ...config.runtime_boundary_policy import flag_enabled

    return flag_enabled("text_guard")


def get_text_block(part) -> str | None:
    if isinstance(part, str):
        return part
    kind = part.get("type") if isinstance(part, dict) else getattr(part, "type", None)
    value = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
    return value if getattr(kind, "value", kind) == "text" and isinstance(value, str) else None


def blocked_reason(parts: list) -> tuple[int, str, str] | None:
    values = [get_text_block(part) for part in parts]
    if any(value is None for value in values):
        return 415, "unsupported-media", "当前样品仅开放文本对话，请移除附件或多媒体后重试。"
    if sum(len(value) for value in values if value is not None) > MAX_INPUT:
        return 422, "input-limit", f"文本超过 {MAX_INPUT} 字符，请缩短后重试。"
    merged = "".join(value for value in values if value is not None)
    separated = "\n".join(value for value in values if value is not None)
    for text in (merged, separated):
        normalized = "".join(ch for ch in unicodedata.normalize("NFKC", text) if unicodedata.category(ch) != "Cf")
        for code, rule in RULES:
            if rule.search(normalized):
                return 403, code, "安全策略拦截了疑似越权指令，请改用正常业务描述。"
    return None


def _audit_rejection(actor: Actor, status: int, reason: str) -> None:
    try:
        with transaction(actor, "chat.input.block"):
            raise Rejected(status, reason, security=status == 403)
    except Rejected:
        pass
    except (OSError, ValueError, sqlite3.Error):
        logger.warning("trusted sample input denial could not be recorded")


async def check_portal_input(parts: list, *, isolated: bool) -> None:
    if not enabled():
        return
    identity = CURRENT_IDENTITY.get()
    if isolated and identity is not None and identity.source == SCHEDULED_SOURCE:
        return  # A verified server job, outside the end-user Portal text profile.
    if not isolated or not production_guards():
        raise HTTPException(503, "文本安全策略要求同时启用会话隔离和生产保护。")
    result = blocked_reason(parts)
    if result is None:
        return
    status, reason, detail = result
    if identity is not None and identity.user_id:
        await asyncio.to_thread(_audit_rejection, Actor(get_userinfo_url(), identity.user_id), status, reason)
    raise HTTPException(status, f"{detail}（规则：{reason}）")
