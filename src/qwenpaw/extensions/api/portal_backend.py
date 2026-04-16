from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, FastAPI, HTTPException, Request

from qwenpaw.config.utils import load_config
from qwenpaw.extensions.api.fault_scenario_service import run_fault_scenario_diagnose
from qwenpaw.extensions.integrations.alarm_workorders.query_alarm_workorders import (
    query_alarm_workorders,
)

router = APIRouter(prefix="/api/portal", tags=["portal"])
app = FastAPI(title="Portal Backend")
FAULT_DISPOSAL_SCRIPT_TIMEOUT_SECONDS = 45
PORTAL_EMPLOYEE_STATUS_IDS = (
    "query",
    "fault",
    "knowledge",
    "resource",
    "inspection",
    "order",
)
PORTAL_EMPLOYEE_STATUS_NAMES = {
    "query": "数据分析员",
    "fault": "故障处置员",
    "knowledge": "知识专员",
    "resource": "资产管理员",
    "inspection": "巡检专员",
    "order": "工单调度员",
}
PORTAL_FAULT_ALERT_LIMIT = 20


def _load_fault_disposal_runtime():
    skill_root = (
        Path(__file__).resolve().parents[2]
        / "agents"
        / "skills"
        / "fault-disposal"
    )
    if str(skill_root) not in sys.path:
        sys.path.insert(0, str(skill_root))

    from runtime.reasoners import CopawReasoner, TemplateReasoner
    from runtime.tool_adapters import FaultDisposalToolbox
    from runtime.router import TicketRouter
    from runtime.models import TicketContext
    from runtime.playbooks import ApplicationTimeoutPlaybook, GenericAlarmPlaybook

    return (
        CopawReasoner,
        TemplateReasoner,
        FaultDisposalToolbox,
        TicketRouter,
        TicketContext,
        ApplicationTimeoutPlaybook,
        GenericAlarmPlaybook,
    )


def _fault_disposal_skill_root() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "agents"
        / "skills"
        / "fault-disposal"
    )


def _fault_disposal_bridge_script() -> Path:
    return _fault_disposal_skill_root() / "scripts" / "chat_skill_bridge.py"


def _compact_ui_message(message: dict) -> dict:
    compact_message = dict(message)
    compact_message["id"] = message.get("id")
    compact_message["type"] = message.get("type")
    compact_message["content"] = message.get("content", "")
    compact_message["processBlocks"] = message.get("processBlocks", []) or []
    compact_message["disposalOperation"] = message.get("disposalOperation")
    compact_message["faultScenarioResult"] = _shape_fault_scenario_result(
        message.get("faultScenarioResult")
    )
    compact_message["timestamp"] = (
        message.get("timestamp") or datetime.now(timezone.utc).isoformat()
    )
    return compact_message


async def _get_workspace_and_session(request: Request):
    from qwenpaw.app.agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    return workspace, workspace.runner.session


def _datetime_to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()
    text = str(value or "").strip()
    return text


def _build_portal_employee_status_payload(
    employee_id: str,
    *,
    available: bool,
    total_chat_count: int,
    active_task_count: int,
    active_chat_count: int,
    alert_count: int,
    latest_session_title: str,
    updated_at: str,
) -> dict[str, Any]:
    urgent = alert_count > 0
    status = "running" if active_task_count > 0 else "idle"
    has_conversation = total_chat_count > 0
    progress = "--"

    if urgent:
        current_job = f"待处理告警 {alert_count} 条"
        work_status = "紧急任务"
        state_label = "紧急任务"
        progress = "0%"
    elif status == "running":
        current_job = (
            f"正在处理 {active_chat_count or active_task_count} 个对话任务"
        )
        work_status = "运行中"
        state_label = "运行中"
        progress = "50%"
    elif has_conversation and latest_session_title:
        current_job = f"最近会话：{latest_session_title}"
        work_status = "待机"
        state_label = "待机"
        progress = "100%"
    else:
        current_job = "暂无对话"
        work_status = "待机"
        state_label = "待机"

    return {
        "employeeId": employee_id,
        "employeeName": PORTAL_EMPLOYEE_STATUS_NAMES.get(employee_id, employee_id),
        "available": available,
        "status": status,
        "urgent": urgent,
        "stateLabel": state_label,
        "workStatus": work_status,
        "progress": progress,
        "currentJob": current_job,
        "hasConversation": has_conversation,
        "totalChatCount": total_chat_count,
        "activeTaskCount": active_task_count,
        "activeChatCount": active_chat_count,
        "alertCount": alert_count,
        "latestSessionTitle": latest_session_title,
        "updatedAt": updated_at,
    }


async def _get_portal_employee_workspace(
    request: Request,
    employee_id: str,
):
    config = load_config()
    profile = config.agents.profiles.get(employee_id)
    if profile is None or not getattr(profile, "enabled", True):
        return None

    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=500,
            detail="MultiAgentManager not initialized",
        )

    try:
        return await manager.get_agent(employee_id)
    except ValueError:
        return None


async def _get_employee_alert_count(employee_id: str) -> int:
    if employee_id != "fault":
        return 0

    result = query_alarm_workorders(PORTAL_FAULT_ALERT_LIMIT)
    items = result.get("items") or []
    return int(result.get("total") or len(items))


async def collect_portal_employee_statuses(
    request: Request,
    *,
    employee_ids: tuple[str, ...] = PORTAL_EMPLOYEE_STATUS_IDS,
) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for employee_id in employee_ids:
        workspace = await _get_portal_employee_workspace(request, employee_id)
        if workspace is None:
            statuses.append(
                _build_portal_employee_status_payload(
                    employee_id,
                    available=False,
                    total_chat_count=0,
                    active_task_count=0,
                    active_chat_count=0,
                    alert_count=0,
                    latest_session_title="",
                    updated_at=now_iso,
                )
            )
            continue

        chats = await workspace.chat_manager.list_chats()
        active_task_keys = set(await workspace.task_tracker.list_active_tasks())
        active_chat_count = sum(1 for chat in chats if chat.id in active_task_keys)
        latest_chat = max(
            chats,
            key=lambda chat: chat.updated_at or chat.created_at,
            default=None,
        )
        latest_session_title = latest_chat.name.strip() if latest_chat else ""
        updated_at = _datetime_to_iso(
            latest_chat.updated_at if latest_chat else now_iso,
        )
        alert_count = await _get_employee_alert_count(employee_id)
        statuses.append(
            _build_portal_employee_status_payload(
                employee_id,
                available=True,
                total_chat_count=len(chats),
                active_task_count=len(active_task_keys),
                active_chat_count=active_chat_count,
                alert_count=alert_count,
                latest_session_title=latest_session_title,
                updated_at=updated_at,
            )
        )

    return statuses


async def _load_portal_fault_history(
    request: Request,
    *,
    session_id: str,
    user_id: str = "default",
) -> list[dict]:
    _workspace, session = await _get_workspace_and_session(request)
    state = await session.get_session_state_dict(session_id, user_id)
    history = state.get("portal_fault_history", {}).get("messages", [])
    return history if isinstance(history, list) else []


async def _save_portal_fault_history(
    request: Request,
    *,
    session_id: str,
    messages: list[dict],
    user_id: str = "default",
) -> None:
    _workspace, session = await _get_workspace_and_session(request)
    await session.update_session_state(
        session_id,
        ["portal_fault_history", "messages"],
        messages,
        user_id=user_id,
    )


def _shape_fault_scenario_result(result: Any) -> dict | None:
    if result is None:
        return None

    payload = result if isinstance(result, dict) else {}
    shaped = dict(payload)
    shaped["summary"] = str(payload.get("summary") or "诊断已完成")
    shaped["rootCause"] = (
        payload.get("rootCause") if isinstance(payload.get("rootCause"), dict) else {}
    )
    shaped["steps"] = payload.get("steps") if isinstance(payload.get("steps"), list) else []
    shaped["logEntries"] = (
        payload.get("logEntries") if isinstance(payload.get("logEntries"), list) else []
    )
    shaped["actions"] = (
        payload.get("actions") if isinstance(payload.get("actions"), list) else []
    )
    return shaped


def _shape_fault_scenario_response(result: dict[str, Any]) -> dict[str, Any]:
    shaped = dict(result)
    shaped["result"] = _shape_fault_scenario_result(result.get("result")) or {
        "summary": "诊断已完成",
        "rootCause": {},
        "steps": [],
        "logEntries": [],
        "actions": [],
    }
    return shaped


def _normalize_portal_fault_history_messages(messages: list[dict]) -> list[dict]:
    return [_compact_ui_message(message) for message in messages if isinstance(message, dict)]


def _build_fault_context(payload: dict, *, source: str = "portal-chat"):
    (
        _CopawReasoner,
        _TemplateReasoner,
        _FaultDisposalToolbox,
        _TicketRouter,
        TicketContext,
        _ApplicationTimeoutPlaybook,
        _GenericAlarmPlaybook,
    ) = _load_fault_disposal_runtime()
    return TicketContext(
        entry_workorder=payload.get("entryWorkorder") or {},
        workorders=payload.get("workorders") or [],
        tags=payload.get("tags") or [],
        alarm_code=payload.get("alarmCode") or "",
        source=payload.get("source") or source,
    )


def _extract_portal_action_from_markdown(markdown_text: str) -> dict | None:
    text = str(markdown_text or "").strip()
    if not text:
        return None

    match = re.search(r"```portal-action\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if not match:
        return None

    try:
        payload = json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return None

    if isinstance(payload, dict):
        payload.setdefault("status", "ready")
        return payload
    return None


def _run_fault_disposal_chat_skill(command: str, payload: dict) -> dict:
    script_path = _fault_disposal_bridge_script()
    if not script_path.exists():
        raise FileNotFoundError(f"fault-disposal chat skill bridge not found: {script_path}")

    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False)
        context_file = handle.name

    try:
        completed = subprocess.run(
            [sys.executable, str(script_path), command, "--context-file", context_file],
            cwd=str(_fault_disposal_skill_root()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=FAULT_DISPOSAL_SCRIPT_TIMEOUT_SECONDS,
            check=False,
        )
    finally:
        try:
            Path(context_file).unlink(missing_ok=True)
        except OSError:
            pass

    stdout_text = (completed.stdout or "").strip()
    stderr_text = (completed.stderr or "").strip()
    if completed.returncode != 0:
        error_text = stderr_text or stdout_text or "fault-disposal skill bridge failed"
        raise RuntimeError(error_text)

    if not stdout_text:
        raise RuntimeError("fault-disposal skill bridge returned empty output")

    message = {
        "kind": "assistant",
        "content": stdout_text,
        "processBlocks": [],
    }
    action = _extract_portal_action_from_markdown(stdout_text)
    if action:
        message["action"] = action

    return {
        "session": {
            "sessionId": payload.get("sessionId") or "",
            "playbookId": payload.get("playbookId") or "",
            "reasoner": "fault-disposal-chat-skill",
        },
        "messages": [message],
        "toolCalls": [],
    }


def _run_fault_disposal_diagnose(payload: dict) -> dict:
    return _run_fault_disposal_chat_skill("diagnose", payload)


def _run_fault_disposal_execute(payload: dict) -> dict:
    return _run_fault_disposal_chat_skill("execute", payload)


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.get("/alarm-workorders")
async def get_alarm_workorders(limit: int = 5):
    try:
        return query_alarm_workorders(max(1, limit))
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_alarm_workorders failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/employee-status")
async def get_portal_employee_statuses(
    request: Request,
):
    try:
        employees = await collect_portal_employee_statuses(request)
        return {
            "employees": employees,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_portal_employee_statuses failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/fault-disposal/recovery-visualization")
async def get_fault_disposal_recovery_visualization(
    payload: dict = Body(default_factory=dict),
):
    try:
        operation = payload.get("operation") or {}
        recovery = payload.get("recovery") or {}
        if not isinstance(operation, dict) or not operation:
            raise ValueError("operation payload is required")

        (
            _CopawReasoner,
            TemplateReasoner,
            FaultDisposalToolbox,
            _TicketRouter,
            _TicketContext,
            _ApplicationTimeoutPlaybook,
            _GenericAlarmPlaybook,
        ) = _load_fault_disposal_runtime()
        toolbox = FaultDisposalToolbox()
        reasoner = TemplateReasoner()

        if not recovery:
            simulated_result, _ = toolbox.execute_kill_slow_sql(operation)
            recovery = simulated_result.get("recovery") or {}

        verification, _ = toolbox.collect_recovery_verification(operation, recovery)
        visualization = reasoner.build_recovery_visualization_payload(
            verification=verification,
            recovery=recovery,
        )
        return {
            "status": "ok",
            "visualization": visualization,
            "verification": verification,
            "recovery": recovery,
        }
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_fault_disposal_recovery_visualization failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/fault-disposal/diagnose")
async def fault_disposal_diagnose(
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    try:
        session_id = str(payload.get("sessionId") or "").strip()
        if not session_id:
            raise ValueError("sessionId is required")
        visible_content = str(payload.get("visibleContent") or "").strip()
        result = _run_fault_disposal_diagnose(payload)
        history = await _load_portal_fault_history(request, session_id=session_id)
        if visible_content:
            history.append(
                _compact_ui_message(
                    {
                        "id": f"user-{datetime.now(timezone.utc).timestamp()}",
                        "type": "user",
                        "content": visible_content,
                    },
                )
            )
        for message in result.get("messages", []) or []:
            history.append(
                _compact_ui_message(
                    {
                        "id": f"agent-{datetime.now(timezone.utc).timestamp()}",
                        "type": "agent",
                        "content": message.get("content", ""),
                        "processBlocks": message.get("processBlocks", []),
                        "disposalOperation": message.get("action"),
                    },
                )
            )
        await _save_portal_fault_history(request, session_id=session_id, messages=history)
        return result
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] fault_disposal_diagnose failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/fault-disposal/execute")
async def fault_disposal_execute(
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    try:
        session_id = str(payload.get("sessionId") or "").strip()
        if not session_id:
            raise ValueError("sessionId is required")
        visible_content = str(payload.get("visibleContent") or "").strip()
        result = _run_fault_disposal_execute(payload)
        history = await _load_portal_fault_history(request, session_id=session_id)
        if visible_content:
            history.append(
                _compact_ui_message(
                    {
                        "id": f"user-{datetime.now(timezone.utc).timestamp()}",
                        "type": "user",
                        "content": visible_content,
                    },
                )
            )
        for message in result.get("messages", []) or []:
            history.append(
                _compact_ui_message(
                    {
                        "id": f"agent-{datetime.now(timezone.utc).timestamp()}",
                        "type": "agent",
                        "content": message.get("content", ""),
                        "processBlocks": message.get("processBlocks", []),
                        "disposalOperation": message.get("action"),
                    },
                )
            )
        await _save_portal_fault_history(request, session_id=session_id, messages=history)
        return result
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] fault_disposal_execute failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.post("/fault-scenarios/diagnose")
async def portal_fault_scenario_diagnose(
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    try:
        session_id = str(payload.get("sessionId") or "").strip()
        if not session_id:
            raise HTTPException(status_code=422, detail="sessionId is required")

        result = _shape_fault_scenario_response(run_fault_scenario_diagnose(payload))
        if hasattr(request.app.state, "multi_agent_manager"):
            history = await _load_portal_fault_history(request, session_id=session_id)
            history.append(
                _compact_ui_message(
                    {
                        "id": f"user-{datetime.now(timezone.utc).timestamp()}",
                        "type": "user",
                        "content": payload.get("content", ""),
                    }
                )
            )
            history.append(
                _compact_ui_message(
                    {
                        "id": f"agent-{datetime.now(timezone.utc).timestamp()}",
                        "type": "agent",
                        "content": result["result"]["summary"],
                        "faultScenarioResult": result["result"],
                    }
                )
            )
            await _save_portal_fault_history(
                request,
                session_id=session_id,
                messages=history,
            )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] portal_fault_scenario_diagnose failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


@router.get("/fault-disposal/history/{session_id}")
async def fault_disposal_history(
    request: Request,
    session_id: str,
):
    try:
        history = await _load_portal_fault_history(request, session_id=session_id)
        return {
            "messages": _normalize_portal_fault_history_messages(history),
            "status": "idle",
        }
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] fault_disposal_history failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


def register_app_routes(fastapi_app) -> None:
    """Register portal routes on the main QwenPaw FastAPI app."""
    fastapi_app.include_router(router)


app.include_router(router)
