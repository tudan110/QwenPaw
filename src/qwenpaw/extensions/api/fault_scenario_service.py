import json
import os
from pathlib import Path

from .fault_scenario_models import FaultScenarioDetection


CMDB_KEYWORDS = ("cmdb",)
CMDB_WRITE_ACTION_KEYWORDS = ("新增", "插入")
DATABASE_FAULT_KEYWORDS = ("mysql", "死锁")
FAILURE_HINT_KEYWORDS = ("失败", "报错", "超时")


def _contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)




def detect_fault_scenario(*, employee_id: str, content: str | None) -> FaultScenarioDetection:
    normalized = str(content or "").strip().lower()
    if employee_id != "fault":
        return FaultScenarioDetection(False, "", "")

    has_cmdb_keyword = _contains_any_keyword(normalized, CMDB_KEYWORDS)
    has_cmdb_write_action = _contains_any_keyword(normalized, CMDB_WRITE_ACTION_KEYWORDS)
    has_database_fault = _contains_any_keyword(normalized, DATABASE_FAULT_KEYWORDS)
    has_failure_hint = _contains_any_keyword(normalized, FAILURE_HINT_KEYWORDS)

    if not (
        (has_cmdb_keyword and has_cmdb_write_action and has_failure_hint)
        or (has_database_fault and (has_cmdb_keyword or has_cmdb_write_action))
    ):
        return FaultScenarioDetection(False, "", "")
    return FaultScenarioDetection(
        triggered=True,
        scene_code="cmdb_add_failed_mysql_deadlock",
        entry_summary="正在关联分析...",
    )


def parse_fault_scenario_output(stdout_text: str) -> dict:
    payload = json.loads(stdout_text)
    payload.setdefault("summary", "诊断已完成")
    payload.setdefault("rootCause", {})
    payload.setdefault("steps", [])
    payload.setdefault("logEntries", [])
    payload.setdefault("actions", [])
    return payload


def _fault_skill_root() -> Path:
    configured_root = os.getenv("QWENPAW_FAULT_SKILL_ROOT", "").strip()
    if configured_root:
        return Path(configured_root)
    return (
        Path(__file__).resolve().parents[4]
        / "deploy-all"
        / "qwenpaw"
        / "working"
        / "workspaces"
        / "fault"
        / "skills"
    )


def run_fault_scenario_diagnose(payload: dict) -> dict:
    session_id = str(payload.get("sessionId") or "").strip()
    if not session_id:
        raise ValueError("sessionId is required")

    detection = detect_fault_scenario(
        employee_id=str(payload.get("employeeId") or "fault"),
        content=payload.get("content"),
    )
    if not detection.triggered:
        raise ValueError("unsupported fault scenario")

    return {
        "session": {
            "sessionId": session_id,
            "scene": detection.scene_code,
        },
        "result": parse_fault_scenario_output(
            json.dumps(
                {
                    "summary": "已建立场景根因分析脚手架，后续将接入 MySQL 死锁证据采集。",
                    "rootCause": {"type": "待分析", "object": "cmdb_device"},
                    "steps": [
                        {"id": "database-analysis", "status": "scaffolded"},
                        {"id": "decision-merge", "status": "scaffolded"},
                    ],
                    "logEntries": [
                        {
                            "stage": "database-analysis",
                            "summary": "MySQL 死锁证据采集尚未接线，当前返回脚手架结果。",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        ),
    }
