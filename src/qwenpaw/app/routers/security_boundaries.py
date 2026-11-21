# -*- coding: utf-8 -*-
"""Administrator view of runtime boundaries and the global delete guard."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool

from ...config.delete_protection import (
    CONFIG_LOCK,
    ENVIRONMENT_LOCK,
    STALE_POLICY,
    DeleteProtectionConflict,
    configure_delete_protection,
    delete_protection_editing_lock,
)
from ...config import online_boundary_settings as online
from ...config.policy_file import PolicyConflict
from ...config.runtime_boundary_policy import RemoteEndpoint, flag_enabled
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


def _delete_snapshot(status: dict) -> dict:
    locked_reason = delete_protection_editing_lock(
        status["blocked"], status["source"],
    )
    return {
        **status, "editable": locked_reason is None, "locked_reason": locked_reason,
    }


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
        "controls": online.controls_snapshot(),
        "delete_protection": _delete_snapshot(_delete_status()),
        "mcp": protection["mcp_boundary"],
        "tool_guard": {
            "enabled": tool_guard.enabled,
            "auto_deny_rule_count": len(tool_guard.auto_denied_rules),
        },
        "output_masking_active": protection["output_guard"]["active"],
        "chat_isolation_enabled": chat_isolation_enabled(),
        "text_guard_configured": text_guard_enabled(),
        "controlled_documents_configured": flag_enabled("controlled_documents"),
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


class ConfigureDeleteProtection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocked: StrictBool
    expected_blocked: StrictBool
    confirm: Literal["启用全局删除保护", "解除全局删除保护"]


def _configuration_actor(request: Request) -> str:
    require_browser_origin(request)
    identity = request.state.access_identity
    if not identity.user_id:
        raise HTTPException(403, "无法确认配置变更主体。")
    return identity.user_id


def _write_delete_policy(
    actor: str, *, blocked: bool, expected_blocked: bool,
) -> dict:
    current = _delete_status()
    if current["source"] != "config_or_default":
        reason = ENVIRONMENT_LOCK if current["source"] == "environment" else CONFIG_LOCK
        raise HTTPException(409, reason)
    if current["blocked"] != expected_blocked:
        raise HTTPException(409, STALE_POLICY)
    try:
        changed = configure_delete_protection(
            blocked=blocked, expected_blocked=expected_blocked,
        )
    except DeleteProtectionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (OSError, ValueError) as exc:
        logger.warning("Global deletion policy write failed: %s", type(exc).__name__)
        raise HTTPException(409, "无法安全写入当前运行配置，请由运维核对。") from exc
    status = _delete_status()
    if changed:
        logger.warning(
            "[SECURITY_CONFIG] actor=%r action=%s previous=%s "
            "configured=%s effective=%s source=%s",
            actor, "enable_delete_protection" if blocked else "disable_delete_protection",
            str(expected_blocked).lower(), str(blocked).lower(),
            status["blocked"], status["source"],
        )
    if status["source"] != "config_or_default" or status["blocked"] != blocked:
        raise HTTPException(409, "未能确认变更已生效，请刷新状态并联系运维核对。")
    return {"delete_protection": status, "changed": changed}


@router.post("/delete-protection/configure")
def configure_global_delete_protection(
    request: Request, body: ConfigureDeleteProtection,
) -> dict:
    actor = _configuration_actor(request)
    expected_confirmation = "启用全局删除保护" if body.blocked else "解除全局删除保护"
    if body.confirm != expected_confirmation:
        raise HTTPException(422, "确认内容与所选操作不一致。")
    result = _write_delete_policy(
        actor, blocked=body.blocked, expected_blocked=body.expected_blocked,
    )
    result["delete_protection"] = _delete_snapshot(result["delete_protection"])
    return result


@router.post("/delete-protection/enable")
def enable_global_delete_protection(
    request: Request, body: EnableDeleteProtection,
) -> dict:
    """Keep the original one-way API for existing clients."""
    actor = _configuration_actor(request)
    current = _delete_status()
    if current["blocked"]:
        return {"delete_protection": current, "changed": False}
    return _write_delete_policy(actor, blocked=True, expected_blocked=False)


BoundaryValue = StrictBool | Literal["block", "warn", "off"] | list[RemoteEndpoint]


class ConfigureBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: BoundaryValue
    expected: BoundaryValue | None
    confirm: Literal["确认变更安全边界"]

    @staticmethod
    def _json_value(value):
        return [entry.model_dump() for entry in value] if isinstance(value, list) else value


@router.post("/settings/{key}/configure")
def configure_boundary(request: Request, key: online.Key, body: ConfigureBoundary) -> dict:
    actor = _configuration_actor(request)
    value = body._json_value(body.value)
    expected = body._json_value(body.expected)
    if any(isinstance(item, list) and len(item) > 64 for item in (value, expected)):
        raise HTTPException(422, "最多可配置 64 条 MCP 端点。")
    try:
        changed = online.configure(key, value, expected)
    except PolicyConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except online.InvalidChange as exc:
        raise HTTPException(409, str(exc)) from exc
    except (OSError, ValueError) as exc:
        # Raw validation errors can include unrelated config values.
        raise HTTPException(409, CONFIG_LOCK) from exc
    try:
        effective = online.confirmed(key, value)
    except (OSError, ValueError, PolicyConflict):
        effective = False
    if changed:
        # MCP identifiers are not copied into the log.
        previous = len(expected) if isinstance(expected, list) else expected
        target = len(value) if isinstance(value, list) else value
        logger.warning(
            "[SECURITY_CONFIG] actor=%r action=configure_boundary key=%s previous=%r configured=%r verified=%s",
            actor, key, previous, target, effective,
        )
    if not effective:
        raise HTTPException(409, "未能确认变更已生效，请刷新后核对。")
    return {"changed": changed}
