from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, FastAPI, HTTPException, Request

from qwenpaw.extensions.integrations.alarm_workorders.query_alarm_workorders import (
    query_alarm_workorders,
)

router = APIRouter(prefix="/api/portal", tags=["portal"])
app = FastAPI(title="Portal Backend")
FAULT_DISPOSAL_SCRIPT_TIMEOUT_SECONDS = 45


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
    return {
        "id": message.get("id"),
        "type": message.get("type"),
        "content": message.get("content", ""),
        "processBlocks": message.get("processBlocks", []) or [],
        "disposalOperation": message.get("disposalOperation"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def _get_workspace_and_session(request: Request):
    from qwenpaw.app.agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    return workspace, workspace.runner.session


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


@router.get("/fault-disposal/history/{session_id}")
async def fault_disposal_history(
    request: Request,
    session_id: str,
):
    try:
        history = await _load_portal_fault_history(request, session_id=session_id)
        return {"messages": history, "status": "idle"}
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] fault_disposal_history failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc


def register_app_routes(fastapi_app) -> None:
    """Register portal routes on the main QwenPaw FastAPI app."""
    fastapi_app.include_router(router)


app.include_router(router)
