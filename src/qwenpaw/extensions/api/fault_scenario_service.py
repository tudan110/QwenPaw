import json
import subprocess
import sys
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

    script_path = (
        _fault_skill_root()
        / "scenario-root-cause-analyst"
        / "scripts"
        / "analyze_scenario.py"
    )
    completed = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        check=True,
        text=True,
    )

    return {
        "session": {
            "sessionId": session_id,
            "scene": "cmdb_add_failed_mysql_deadlock",
        },
        "result": parse_fault_scenario_output(completed.stdout),
    }
