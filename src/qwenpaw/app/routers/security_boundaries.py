# -*- coding: utf-8 -*-
"""Administrator view of runtime boundaries and narrow hardening controls."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from ...constant import EnvVarLoader
from ...extensions.api.access_policy import require_browser_origin
from ...extensions.api.delete_block_middleware import resolve_delete_ops_policy
from .security_evidence import get_protection, require_evidence_admin

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/security/boundaries",
    tags=["security-boundaries"],
    dependencies=[Depends(require_evidence_admin)],
)


def _delete_status() -> dict:
    blocked, source = resolve_delete_ops_policy()
    return {"blocked": blocked, "source": source}


@router.get("")
def get_boundaries() -> dict:
    from ...extensions.api.chat_isolation import chat_isolation_enabled
    from ...extensions.api.domain_guard import load_config as load_domain_config
    from ...extensions.api.trusted_chat_text import enabled as text_guard_enabled
    from ...security.skill_scanner import _get_scan_mode
    from ...security.tool_guard.engine import get_guard_engine

    protection = get_protection()
    tool_guard = get_guard_engine()
    return {
        "queried_at": protection["queried_at"],
        "scope": "current_backend_configuration",
        "delete_protection": _delete_status(),
        "mcp": protection["mcp_boundary"],
        "tool_guard": {
            "enabled": tool_guard.enabled,
            "auto_deny_rule_count": len(tool_guard.auto_denied_rules),
        },
        "output_masking_active": protection["output_guard"]["active"],
        "chat_isolation_enabled": chat_isolation_enabled(),
        "text_guard_configured": text_guard_enabled(),
        "controlled_documents_configured": EnvVarLoader.get_str(
            "QWENPAW_CONTROLLED_DOCUMENTS", "false",
        ).strip().lower() in {"true", "1", "yes", "on"},
        "global_skill_scan_mode": _get_scan_mode(),
        "domain_guard_mode": load_domain_config().mode,
    }


@router.get("/delete-protection/check")
def check_knowledge_deletion() -> dict:
    """Run the knowledge base's actual policy gate without accessing data."""
    from ...extensions.integrations.knowledge_source_control import (
        check_source_operation_policy,
    )

    try:
        check_source_operation_policy("delete")
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        decision = "blocked"
    else:
        decision = "not_blocked"
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "scope": "knowledge_base_policy_only",
        "decision": decision,
    }


class EnableDeleteProtection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: Literal["启用全局删除保护"]


@router.post("/delete-protection/enable")
def enable_global_delete_protection(
    request: Request,
    body: EnableDeleteProtection,
) -> dict:
    from ...config.delete_protection import (
        DeleteProtectionConflict,
        enable_delete_protection,
    )

    require_browser_origin(request)
    identity = request.state.access_identity
    if not identity.user_id:
        raise HTTPException(403, "无法确认配置变更主体。")
    current = _delete_status()
    if current["blocked"]:
        return {"delete_protection": current, "changed": False}
    try:
        changed = enable_delete_protection()
    except DeleteProtectionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (OSError, ValueError) as exc:
        logger.warning("Global deletion policy write failed: %s", type(exc).__name__)
        raise HTTPException(409, "无法安全写入当前运行配置，请由运维核对。") from exc
    status = _delete_status()
    if changed:
        logger.warning(
            "[SECURITY_CONFIG] actor=%r action=enable_delete_protection "
            "previous=false configured=true effective=%s source=%s",
            identity.user_id, status["blocked"], status["source"],
        )
    if not status["blocked"]:
        raise HTTPException(409, "未能确认正在生效，请刷新状态并联系运维核对。")
    return {"delete_protection": status, "changed": changed}
