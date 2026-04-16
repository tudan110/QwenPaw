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


def run_fault_scenario_diagnose(payload: dict) -> dict:
    session_id = str(payload.get("sessionId") or "").strip()
    if not session_id:
        raise ValueError("sessionId is required")

    return {
        "session": {
            "sessionId": session_id,
            "scene": "cmdb_add_failed_mysql_deadlock",
        },
        "result": {
            "summary": "已定位为数据库死锁导致 CMDB 新增失败",
            "rootCause": {"type": "数据库异常"},
            "steps": [],
            "logEntries": [],
        },
    }
