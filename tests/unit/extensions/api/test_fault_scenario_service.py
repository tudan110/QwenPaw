from pathlib import Path

import pytest

from qwenpaw.extensions.api.fault_scenario_service import (
    _fault_skill_root,
    detect_fault_scenario,
    parse_fault_scenario_output,
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


def test_parse_fault_scenario_output_keeps_root_cause_and_logs() -> None:
    payload = parse_fault_scenario_output(
        """
        {"summary":"已定位为数据库死锁导致 CMDB 新增失败",
         "rootCause":{"type":"数据库异常","object":"cmdb_device"},
         "steps":[{"id":"database-analysis","status":"success"}],
         "logEntries":[{"stage":"database-analysis","summary":"捕获锁等待"}]}
        """
    )

    assert payload["rootCause"]["object"] == "cmdb_device"
    assert payload["logEntries"][0]["stage"] == "database-analysis"


def test_fault_skill_root_prefers_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QWENPAW_FAULT_SKILL_ROOT", "/configured/fault-skills")

    assert _fault_skill_root() == Path("/configured/fault-skills")


def test_run_fault_scenario_diagnose_returns_scaffold_result_without_shelling_out(
) -> None:
    payload = run_fault_scenario_diagnose({"sessionId": "fault-scenario-1"})

    assert payload["session"]["sessionId"] == "fault-scenario-1"
    assert payload["session"]["scene"] == "cmdb_add_failed_mysql_deadlock"
    assert "脚手架" in payload["result"]["summary"]
    assert payload["result"]["rootCause"]["object"] == "cmdb_device"
    assert payload["result"]["steps"][0]["status"] == "scaffolded"
    assert payload["result"]["logEntries"][0]["stage"] == "database-analysis"
