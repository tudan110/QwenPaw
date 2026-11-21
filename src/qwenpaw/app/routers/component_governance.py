# -*- coding: utf-8 -*-
"""Administrator view of managed component changes, scans and local policy."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .security_evidence import require_evidence_admin
from ..utils import schedule_agent_reload
from ...extensions.api.access_policy import require_browser_origin
from ...extensions.security import call_admission
from ...governance import component_disposition, component_events, component_scan
from ...local_models.resource_policy import (
    is_loopback_endpoint,
    runtime_authenticated,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/security/governance",
    tags=["component-governance"],
    dependencies=[Depends(require_evidence_admin)],
)
_scan_lock = asyncio.Lock()


@router.get("/changes")
def changes(
    view: Literal["supply", "config"] = "config",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    try:
        payload = component_events.list_changes(
            supply=view == "supply", limit=limit, offset=offset
        )
        names = _workspace_names({row["scope"] for row in payload["records"]})
        for row in payload["records"]:
            row["scope_name"] = _scope_name(row["scope"], names)
        return payload
    except (sqlite3.Error, OSError, ValueError) as exc:
        logger.exception("Cannot read component change storage")
        raise HTTPException(503, "组件审计存储不可读") from exc


def _workspaces() -> dict[str, Path]:
    from ...config import load_config

    return {
        key: Path(profile.workspace_dir).expanduser()
        for key, profile in sorted(load_config().agents.profiles.items())
        if profile.workspace_dir
    }


_WORKSPACE_NAMES = {
    "global": "全局",
    "gateway": "智观AI",
    "fault": "故障分析专家",
    "order": "工单处置专员",
    "query": "数据分析专家",
    "resource": "资产管理专员",
    "inspection": "运维巡检专员",
    "knowledge": "知识库助手",
    "operator": "操作助手",
    "fde": "技能构建助手",
    "default": "默认助手",
}
_ORGANIZATION_SCOPES = {"全局", "全局部署", "技能池"}


def _workspace_names(
    scopes: set[str], workspaces: dict[str, Path] | None = None,
) -> dict[str, str]:
    if workspaces is None:
        workspaces = _workspaces()
    names = dict(_WORKSPACE_NAMES)
    for scope in (scopes & workspaces.keys()) - {"gateway", "global"}:
        try:
            payload = json.loads(
                (workspaces[scope] / "agent.json").read_text(encoding="utf-8"),
            )
        except (OSError, ValueError):
            continue  # A missing profile must not hide historical evidence.
        raw = payload.get("name") if isinstance(payload, dict) else None
        if not isinstance(raw, str):
            continue
        name = raw.strip()
        if name.casefold() in {scope.casefold(), "qwenpaw", "portal", "gateway"}:
            continue
        display_name = component_events.label(name)
        if display_name != "[标识已隐藏]":
            names[scope] = display_name
    return names


def _scope_name(scope: str, names: dict[str, str]) -> str:
    if scope in _ORGANIZATION_SCOPES or (
        scope.startswith("技能池 ") and scope.removeprefix("技能池 ").isdecimal()
    ):
        return scope
    return names.get(scope, "数字员工")


def _scan_view(report: dict | None, workspaces: dict[str, Path]) -> dict:
    result = component_disposition.with_actions(report, workspaces)
    if result:
        names = _workspace_names({row["scope"] for row in result["rows"]}, workspaces)
        for row in result["rows"]:
            row["scope_name"] = _scope_name(row["scope"], names)
    return {"report": result}


@router.get("/scan")
def scan_report() -> dict:
    try:
        return _scan_view(component_events.latest_scan(), _workspaces())
    except (sqlite3.Error, OSError, ValueError, call_admission.PolicyUnavailable) as exc:
        logger.exception("Cannot read component scan storage")
        raise HTTPException(503, "扫描结果或处置状态不可读") from exc


def _scan_and_save(provider_manager) -> dict:
    from ...agents.skill_system.store import get_skill_pool_dirs

    workspaces = _workspaces()
    report = component_scan.run_scan(provider_manager, list(workspaces.items()), get_skill_pool_dirs())
    component_events.save_scan(report)
    return _scan_view(report, workspaces)


@router.post("/scan", dependencies=[Depends(require_browser_origin)])
async def scan(request: Request) -> dict:
    if _scan_lock.locked():
        raise HTTPException(409, "已有扫描进行中，请稍后刷新结果")
    async with _scan_lock:
        try:
            return await asyncio.to_thread(
                _scan_and_save, request.app.state.provider_manager
            )
        except Exception as exc:
            logger.exception("Component scan could not be completed")
            raise HTTPException(
                503, "未取得完整扫描报告，未覆盖原报告"
            ) from exc


class Disposition(BaseModel):
    checked_at: str = Field(min_length=1, max_length=60)
    index: int = Field(ge=0)


def _apply_disposition(body: Disposition, actor: str) -> tuple[dict, str | None]:
    workspaces = _workspaces()
    report = component_events.latest_scan()
    if not report or report["checked_at"] != body.checked_at or body.index >= len(report["rows"]):
        raise HTTPException(409, "扫描报告已更新，请刷新后重新选择处置项。")
    result = component_disposition.with_actions(report, workspaces)
    try:
        message, reload_scope = component_disposition.apply(result, body.index, workspaces, actor=actor)
    except (ValueError, call_admission.PolicyConflict) as exc:
        raise HTTPException(409, str(exc) or "组件策略已变化，请刷新后重试。") from exc
    return {**_scan_view(report, workspaces), "message": message}, reload_scope


@router.post("/scan/disposition", dependencies=[Depends(require_browser_origin)])
async def apply_disposition(request: Request, body: Disposition) -> dict:
    if _scan_lock.locked():
        raise HTTPException(409, "正在扫描或处置，请刷新后重试。")
    async with _scan_lock:
        actor = component_events.actor.get() or f"inoe:{request.state.access_identity.user_id}"
        try:
            result, reload_scope = await asyncio.to_thread(_apply_disposition, body, actor)
        except (sqlite3.Error, OSError, call_admission.PolicyUnavailable) as exc:
            logger.exception("Unable to apply component disposition")
            raise HTTPException(503, "无法确认处置结果，请刷新后核对状态。") from exc
        if reload_scope:
            schedule_agent_reload(request, reload_scope)
        return result


class LocalAccessUpdate(BaseModel):
    mode: Literal["managed", "deny"]
    allow_downloads: bool | None = None


@router.get("/local-access")
def local_access(request: Request) -> dict:
    manager = request.app.state.local_model_manager
    status = manager.get_llamacpp_server_status()
    provider_manager = request.app.state.provider_manager
    external = False
    active = provider_manager.get_active_model()
    provider = (
        provider_manager.get_provider(active.provider_id) if active else None
    )
    if provider and provider.id != "qwenpaw-local":
        external = bool(
            provider.is_local or is_loopback_endpoint(provider.base_url)
        )
    config = manager.get_config()
    return {
        "mode": config.access_mode,
        "allow_downloads": config.allow_downloads,
        "running": bool(status.get("running")),
        "authenticated": bool(
            status.get("running") and runtime_authenticated(status.get("port"))
        ),
        "filesystem_supported": os.name == "posix",
        "external_local_detected": external,
    }


@router.put("/local-access", dependencies=[Depends(require_browser_origin)])
async def put_local_access(request: Request, body: LocalAccessUpdate) -> dict:
    try:
        await request.app.state.local_model_manager.set_access_policy(
            body.mode, allow_downloads=body.allow_downloads,
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return local_access(request)


@router.post("/local-access/stop", dependencies=[Depends(require_browser_origin)])
async def stop_local_runtime(request: Request) -> dict:
    from .local_models import stop_llamacpp_server

    await stop_llamacpp_server(
        request.app.state.local_model_manager, request.app.state.provider_manager,
    )
    return local_access(request)
