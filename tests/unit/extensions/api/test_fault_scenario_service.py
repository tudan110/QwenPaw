from pathlib import Path

import pytest

from qwenpaw.extensions.api.fault_scenario_service import (
    _parse_alarm_dispatch_context,
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


def test_detect_fault_scenario_does_not_trigger_for_plain_fault_question() -> None:
    detection = detect_fault_scenario(
        employee_id="fault",
        content="帮我看一下今天的告警情况",
    )

    assert detection.triggered is False


def test_run_fault_scenario_diagnose_requires_session_id() -> None:
    with pytest.raises(ValueError, match="sessionId is required"):
        run_fault_scenario_diagnose({})


def test_run_fault_scenario_diagnose_rejects_non_matching_fault_payload() -> None:
    with pytest.raises(ValueError, match="unsupported fault scenario"):
        run_fault_scenario_diagnose(
            {
                "sessionId": "fault-scenario-1",
                "employeeId": "fault",
                "content": "帮我看一下 Redis 命中率",
            }
        )


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


def test_parse_fault_scenario_output_defaults_partial_status() -> None:
    payload = parse_fault_scenario_output('{"summary":"部分完成"}')

    assert payload["steps"] == []
    assert payload["logEntries"] == []


def test_fault_skill_root_prefers_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QWENPAW_FAULT_SKILL_ROOT", "/configured/fault-skills")

    assert _fault_skill_root() == Path("/configured/fault-skills")


def test_parse_alarm_dispatch_context_extracts_res_id_and_event_time() -> None:
    context = _parse_alarm_dispatch_context(
        "数据库锁异常（db_mysql_001 10.43.150.186）\n资源 ID（CI ID）：3094\n告警时间：2026-04-20 18:39:19"
    )

    assert context["res_id"] == "3094"
    assert context["event_time"] == "2026-04-20 18:39:19"
    assert context["manage_ip"] == "10.43.150.186"


def test_run_fault_scenario_diagnose_uses_alarm_analyst_when_res_id_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.extensions.api.fault_scenario_service._run_alarm_analyst_context",
        lambda payload: {
            "summary": "已完成拓扑关联告警与指标联合分析。",
            "rootCause": {"type": "mysql", "object": "db_mysql_001"},
            "steps": [{"id": "cmdb-topology", "status": "success"}],
            "logEntries": [{"stage": "related-alarms", "summary": "已查询关联告警"}],
            "actions": [],
        },
    )

    payload = run_fault_scenario_diagnose(
        {
            "sessionId": "fault-scenario-1",
            "employeeId": "fault",
            "content": "数据库锁异常（db_mysql_001 10.43.150.186）\n资源 ID（CI ID）：3094\n告警时间：2026-04-20 18:39:19",
        }
    )

    assert payload["session"]["sessionId"] == "fault-scenario-1"
    assert payload["session"]["scene"] == "cmdb_add_failed_mysql_deadlock"
    assert "联合分析" in payload["result"]["summary"]
    assert payload["result"]["rootCause"]["object"] == "db_mysql_001"
    assert payload["result"]["steps"][0]["status"] == "success"
    assert payload["result"]["logEntries"][0]["stage"] == "related-alarms"


def test_run_fault_scenario_diagnose_returns_scaffold_when_res_id_missing() -> None:
    payload = run_fault_scenario_diagnose(
        {
            "sessionId": "fault-scenario-1",
            "employeeId": "fault",
            "content": "CMDB 添加设备失败了，怀疑 mysql 死锁，帮我分析一下",
        }
    )

    assert "资源 ID" in payload["result"]["summary"]
    assert payload["result"]["steps"][0]["status"] == "scaffolded"
