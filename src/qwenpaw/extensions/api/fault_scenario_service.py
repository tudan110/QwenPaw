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