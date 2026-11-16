"""Administrator emergency controls; never infer authority from body fields."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...extensions.security.execution_control import (
    cancel_executions,
    get_control_store,
)
from ..task_tracker import stop_all_tracked_tasks

router = APIRouter(prefix="/security/control", tags=["security"])


def _admin(request: Request):
    identity = getattr(request.state, "access_identity", None)
    if identity is None or not identity.is_admin:
        raise HTTPException(403, "执行控制仅允许可信 AI 管理员操作")
    return identity


class ControlAction(BaseModel):
    expected_epoch: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=500)


@router.get("")
async def status(request: Request):
    _admin(request)
    return get_control_store().snapshot()


@router.post("/freeze")
async def freeze(request: Request, action: ControlAction):
    identity = _admin(request)
    try:
        # Persist denial of new admissions BEFORE touching running work.
        state = get_control_store().transition(
            True, action.reason, action.expected_epoch, identity.user_id
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    from ..approvals import get_approval_service

    invalidated = await get_approval_service().cancel_all_pending()
    tasks = await stop_all_tracked_tasks()
    cancelled = cancel_executions()
    return {
        **state,
        "tasks": tasks,
        "executor_cancel_requests": cancelled,
        "approvals_invalidated": invalidated,
        "remote_effects": "unknown",
        "message": "已冻结新执行并请求停止；远端副作用需另行核验",
    }


@router.post("/unfreeze")
async def unfreeze(request: Request, action: ControlAction):
    identity = _admin(request)
    try:
        return get_control_store().transition(
            False, action.reason, action.expected_epoch, identity.user_id
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/tasks/{run_key}")
async def task_status(request: Request, run_key: str, namespace: str):
    _admin(request)
    from ..task_tracker import _TRACKERS

    for tracker in list(_TRACKERS):
        if tracker.namespace == namespace:
            return await tracker.get_control_status(run_key)
    result = get_control_store().task_state(namespace, run_key)
    if result["status"] in {"running", "stop_requested"}:
        result["status"] = "interrupted_unknown"
    return result


@router.get("/audit-status")
async def audit_status(request: Request):
    _admin(request)
    from ...governance.audit import AuditLog

    return AuditLog.get_instance().archive_status()
