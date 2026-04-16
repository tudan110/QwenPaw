import json
import os
from pathlib import Path

from .fault_scenario_models import FaultScenarioDetection




def detect_fault_scenario(*, employee_id: str, content: str | None) -> FaultScenarioDetection:
    normalized = str(content or "").strip().lower()
    if employee_id != "fault":
        return FaultScenarioDetection(False, "", "")
    if "cmdb" not in normalized or ("死锁" not in normalized and "mysql" not in normalized):
        return FaultScenarioDetection(False, "", "")
    return FaultScenarioDetection(
        triggered=True,
        scene_code="cmdb_add_failed_mysql_deadlock",
        entry_summary="正在关联分析...",
    )


def parse_fault_scenario_output(stdout_text: str) -> dict:
    payload = json.loads(stdout_text)
    payload.setdefault("steps", [])
    payload.setdefault("logEntries", [])
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

    return {
        "session": {
            "sessionId": session_id,
            "scene": "cmdb_add_failed_mysql_deadlock",
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
