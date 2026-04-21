from pathlib import Path

import pytest

from qwenpaw.extensions.api.alarm_analyst_service import (
    _fault_skill_root,
    parse_alarm_dispatch_context,
    run_alarm_analyst_diagnose,
)


def test_alarm_analyst_service_fault_skill_root_prefers_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_FAULT_SKILL_ROOT", "/configured/fault-skills")

    assert _fault_skill_root() == Path("/configured/fault-skills")


def test_parse_alarm_dispatch_context_extracts_res_id_and_event_time() -> None:
    context = parse_alarm_dispatch_context(
        "数据库锁异常（db_mysql_001 10.43.150.186）\n资源 ID（CI ID）：3094\n告警时间：2026-04-20 18:39:19"
    )

    assert context["res_id"] == "3094"
    assert context["event_time"] == "2026-04-20 18:39:19"
    assert context["manage_ip"] == "10.43.150.186"


def test_run_alarm_analyst_diagnose_requires_session_id() -> None:
    with pytest.raises(ValueError, match="sessionId is required"):
        run_alarm_analyst_diagnose({})
