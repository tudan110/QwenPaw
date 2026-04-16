import pytest

from qwenpaw.extensions.api.fault_scenario_service import (
    detect_fault_scenario,
    run_fault_scenario_diagnose,
)


def test_detect_fault_scenario_matches_fault_chat_deadlock_keywords() -> None:
    detection = detect_fault_scenario(
        employee_id="fault",
        content="CMDB 添加设备失败了，怀疑 mysql 死锁，帮我分析一下",
    )

    assert detection.triggered is True
    assert detection.scene_code == "cmdb_add_failed_mysql_deadlock"
    assert detection.entry_summary == "正在关联分析..."


def test_detect_fault_scenario_ignores_non_fault_employee() -> None:
    detection = detect_fault_scenario(
        employee_id="query",
        content="CMDB 添加设备失败了，怀疑 mysql 死锁",
    )

    assert detection.triggered is False
    assert detection.scene_code == ""


def test_run_fault_scenario_diagnose_requires_session_id() -> None:
    with pytest.raises(ValueError, match="sessionId is required"):
        run_fault_scenario_diagnose({})
