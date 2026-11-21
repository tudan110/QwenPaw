# -*- coding: utf-8 -*-
"""Administrator view of managed component changes, scans and local policy."""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from .security_evidence import require_evidence_admin
from ...extensions.api.access_policy import require_browser_origin
from ...governance import component_events, component_scan
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
        return component_events.list_changes(
            supply=view == "supply", limit=limit, offset=offset
        )
    except (sqlite3.Error, OSError, ValueError) as exc:
        logger.exception("Cannot read component change storage")
        raise HTTPException(503, "组件审计存储不可读") from exc


@router.get("/scan")
def scan_report() -> dict:
    try:
        return {"report": component_events.latest_scan()}
    except (sqlite3.Error, OSError, ValueError) as exc:
        logger.exception("Cannot read component scan storage")
        raise HTTPException(503, "扫描结果不可读") from exc


def _scan_and_save(provider_manager) -> dict:
    from ...agents.skill_system.store import get_skill_pool_dirs
    from ...config import load_config

    profiles = load_config().agents.profiles
    workspaces = [
        (key, Path(profile.workspace_dir).expanduser())
        for key, profile in sorted(profiles.items())
        if profile.workspace_dir
    ]
    report = component_scan.run_scan(
        provider_manager, workspaces, get_skill_pool_dirs()
    )
    component_events.save_scan(report)
    return {"report": report}


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


class LocalAccessUpdate(BaseModel):
    mode: Literal["managed", "deny"]


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
    return {
        "mode": manager.get_config().access_mode,
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
        await request.app.state.local_model_manager.set_access_mode(body.mode)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return local_access(request)
