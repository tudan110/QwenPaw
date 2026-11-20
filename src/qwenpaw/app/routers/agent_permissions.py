"""Scoped permission inventory and consent for the selected Portal agent."""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..agent_context import get_agent_for_request
from ...agents.skill_system import resolve_effective_skills
from ...constant import WORKING_DIR
from ...extensions.api.access_session import CURRENT_IDENTITY
from ...extensions.api.chat_isolation import chat_scope
from ...extensions.security import portal_capabilities as permissions

router = APIRouter(prefix="/portal/agent-permissions", tags=["agent-permissions"])


class Change(BaseModel):
    kind: Literal["skill", "mcp"]
    name: str = Field(min_length=1, max_length=200)
    mode: Literal["default", "revoked", "temporary"]


class Consent(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    decision: Literal["allow", "deny"]


def _scope():
    identity = CURRENT_IDENTITY.get()
    if identity is None or identity.source not in {"inoe", "qwenpaw", "mixed"} or not identity.user_id:
        raise HTTPException(401, "需要智观用户身份")
    scope = chat_scope()
    if scope is None:
        raise HTTPException(503, "智能体个人权限需要启用 Portal 会话隔离")
    return scope


async def _configured(workspace) -> list[dict]:
    skills = await asyncio.to_thread(
        resolve_effective_skills, workspace.workspace_dir or WORKING_DIR, "console",
    )
    items = [{"kind": "skill", "name": name, "configured": True} for name in sorted(set(skills))]
    manager = workspace.driver_manager
    if manager is not None:
        drivers = await manager.list_drivers(protocol="mcp")
        items.extend({"kind": "mcp", "name": driver.name,
                      "configured": driver.enabled and driver.status == "active"}
                     for driver in drivers if driver.protocol == "mcp")
    return items


@router.get("")
async def inventory(request: Request) -> dict:
    scope = _scope()
    workspace = await get_agent_for_request(request)
    configured = await _configured(workspace)
    settings = await asyncio.to_thread(permissions.settings, scope.owner, workspace.agent_id)
    for item in configured:
        key = item["kind"], item["name"]
        item["mode"], item["expires_at"] = settings.get(key, ("ask" if key[0] == "mcp" else "inherited", None))
    return {"agent_id": workspace.agent_id, "items": configured}


@router.post("")
async def change(request: Request, body: Change) -> dict:
    scope = _scope()
    workspace = await get_agent_for_request(request)
    if not any(item["configured"] and item["kind"] == body.kind and item["name"] == body.name
               for item in await _configured(workspace)):
        raise HTTPException(404, "该智能体未开放此能力")
    await asyncio.to_thread(permissions.change, scope.owner, workspace.agent_id, body.kind, body.name, body.mode)
    return {"ok": True}


@router.get("/requests")
async def requests(request: Request, session_id: str = Query(min_length=1, max_length=256)) -> dict:
    scope = _scope()
    workspace = await get_agent_for_request(request)
    invocation = permissions.PortalInvocation(scope.owner, workspace.agent_id, scope.session_id(session_id))
    return {"items": await asyncio.to_thread(permissions.pending, invocation)}


@router.post("/requests/{request_id}")
async def decision(request: Request, request_id: str, body: Consent) -> dict:
    scope = _scope()
    workspace = await get_agent_for_request(request)
    invocation = permissions.PortalInvocation(scope.owner, workspace.agent_id, scope.session_id(body.session_id))
    if not await asyncio.to_thread(permissions.answer, invocation, request_id, body.decision):
        raise HTTPException(409, "此授权请求已处理、已结束或不属于当前会话")
    return {"ok": True}
