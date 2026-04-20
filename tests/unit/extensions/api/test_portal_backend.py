# -*- coding: utf-8 -*-
"""Tests for portal employee runtime status aggregation."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from qwenpaw.app.runner.models import ChatSpec
from qwenpaw.extensions.api import portal_backend


class _FakeChatManager:
    def __init__(self, chats: list[ChatSpec]) -> None:
        self._chats = chats

    async def list_chats(self) -> list[ChatSpec]:
        return self._chats


class _FakeTaskTracker:
    def __init__(self, active_tasks: list[str]) -> None:
        self._active_tasks = active_tasks

    async def list_active_tasks(self) -> list[str]:
        return self._active_tasks


class _FakeManager:
    def __init__(self, workspaces: dict[str, object]) -> None:
        self._workspaces = workspaces

    async def get_agent(self, agent_id: str):
        workspace = self._workspaces.get(agent_id)
        if workspace is None:
            raise ValueError(f"Agent '{agent_id}' not found")
        return workspace


def _make_request(manager: _FakeManager):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(multi_agent_manager=manager),
        )
    )


@pytest.mark.asyncio
async def test_collect_portal_employee_statuses_uses_runtime_and_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    query_chat = ChatSpec(
        id="query-chat-1",
        name="CPU 使用率分析",
        session_id="console:default",
        user_id="default",
        channel="console",
        updated_at=now,
    )
    fault_chat = ChatSpec(
        id="fault-chat-1",
        name="端口 down 定位",
        session_id="console:default",
        user_id="default",
        channel="console",
        updated_at=now,
    )

    query_workspace = SimpleNamespace(
        chat_manager=_FakeChatManager([query_chat]),
        task_tracker=_FakeTaskTracker(["query-chat-1"]),
    )
    fault_workspace = SimpleNamespace(
        chat_manager=_FakeChatManager([fault_chat]),
        task_tracker=_FakeTaskTracker([]),
    )
    manager = _FakeManager(
        {
            "query": query_workspace,
            "fault": fault_workspace,
        }
    )

    monkeypatch.setattr(
        portal_backend,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                profiles={
                    "query": SimpleNamespace(enabled=True),
                    "fault": SimpleNamespace(enabled=True),
                }
            )
        ),
    )
    monkeypatch.setattr(
        portal_backend,
        "query_alarm_workorders",
        lambda _limit: {"total": 2, "items": [], "source": "mock"},
    )

    statuses = await portal_backend.collect_portal_employee_statuses(
        _make_request(manager),
        employee_ids=("query", "fault", "resource"),
    )
    by_id = {item["employeeId"]: item for item in statuses}

    assert by_id["query"]["available"] is True
    assert by_id["query"]["employeeName"] == "数据分析员"
    assert by_id["query"]["status"] == "running"
    assert by_id["query"]["urgent"] is False
    assert by_id["query"]["currentJob"] == "正在处理 1 个对话任务"
    assert by_id["query"]["latestSessionTitle"] == "CPU 使用率分析"

    assert by_id["fault"]["available"] is True
    assert by_id["fault"]["employeeName"] == "故障处置员"
    assert by_id["fault"]["status"] == "idle"
    assert by_id["fault"]["urgent"] is True
    assert by_id["fault"]["alertCount"] == 2
    assert by_id["fault"]["workStatus"] == "紧急任务"

    assert by_id["resource"]["available"] is False
    assert by_id["resource"]["employeeName"] == "资产管理员"
    assert by_id["resource"]["status"] == "idle"
    assert by_id["resource"]["currentJob"] == "暂无对话"


def test_build_portal_employee_status_payload_prefers_recent_session_for_idle() -> None:
    payload = portal_backend._build_portal_employee_status_payload(
        "knowledge",
        available=True,
        total_chat_count=3,
        active_task_count=0,
        active_chat_count=0,
        alert_count=0,
        latest_session_title="Oracle 死锁方案",
        updated_at="2026-01-02T03:04:05+00:00",
    )

    assert payload["status"] == "idle"
    assert payload["employeeName"] == "知识专员"
    assert payload["urgent"] is False
    assert payload["workStatus"] == "待机"
    assert payload["currentJob"] == "最近会话：Oracle 死锁方案"


def test_fault_scenario_diagnose_route_returns_structured_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)

    monkeypatch.setattr(
        portal_backend,
        "run_fault_scenario_diagnose",
        lambda payload: {
            "session": {
                "sessionId": payload["sessionId"],
                "scene": "cmdb_add_failed_mysql_deadlock",
            },
            "result": {
                "summary": "已定位为数据库死锁导致 CMDB 新增失败",
                "rootCause": {"type": "数据库异常"},
                "steps": [{"id": "database-analysis", "status": "success"}],
                "logEntries": [{"stage": "database-analysis", "summary": "锁等待命中"}],
            },
        },
    )

    response = client.post(
        "/api/portal/fault-scenarios/diagnose",
        json={
            "sessionId": "fault-scenario-1",
            "employeeId": "fault",
            "content": "CMDB 添加失败，怀疑 mysql 死锁",
        },
    )

    assert response.status_code == 200
    assert response.json()["result"]["rootCause"]["type"] == "数据库异常"


def test_real_alarms_route_returns_backend_payload(monkeypatch) -> None:
    client = TestClient(portal_backend.app)
    received: dict[str, int] = {}

    monkeypatch.setattr(
        portal_backend,
        "query_portal_real_alarms",
        lambda limit: received.setdefault("limit", limit) and {
            "total": 1,
            "items": [
                {
                    "id": "mock-deadlock-1",
                    "title": "数据库锁异常",
                    "level": "critical",
                    "status": "active",
                    "eventTime": "2026-04-15 19:20:00",
                    "timeLabel": "2026-04-15 19:20:00",
                    "deviceName": "MySQL",
                    "manageIp": "10.43.150.186",
                    "employeeId": "fault",
                    "dispatchContent": "mysql/死锁 + cmdb/新增/插入",
                    "visibleContent": "数据库锁异常（MySQL 10.43.150.186）",
                }
            ],
            "source": "mock",
        },
    )

    response = client.get("/api/portal/real-alarms?limit=8")

    assert response.status_code == 200
    assert received["limit"] == 8
    assert response.json()["source"] == "mock"
    assert response.json()["items"][0]["employeeId"] == "fault"


def test_real_alarms_route_returns_500_when_backend_query_fails(monkeypatch) -> None:
    client = TestClient(portal_backend.app)

    def _raise(limit: int) -> dict:
        raise RuntimeError("unexpected backend failure")

    monkeypatch.setattr(portal_backend, "query_portal_real_alarms", _raise)

    response = client.get("/api/portal/real-alarms?limit=8")

    assert response.status_code == 500
    assert response.json()["detail"] == "RuntimeError: unexpected backend failure"


def test_real_alarms_route_keeps_alarm_workorders_route_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)

    monkeypatch.setattr(
        portal_backend,
        "query_alarm_workorders",
        lambda limit: {"total": 2, "items": [{"id": "wo-1"}], "source": "mock"},
    )
    monkeypatch.setattr(
        portal_backend,
        "query_portal_real_alarms",
        lambda limit: {"total": 1, "items": [{"id": "alarm-1"}], "source": "mock"},
    )

    workorders_response = client.get("/api/portal/alarm-workorders?limit=5")
    real_alarms_response = client.get("/api/portal/real-alarms?limit=5")

    assert workorders_response.status_code == 200
    assert real_alarms_response.status_code == 200
    assert workorders_response.json()["total"] == 2
    assert real_alarms_response.json()["total"] == 1


def test_fault_scenario_diagnose_route_rejects_missing_session_id() -> None:
    client = TestClient(portal_backend.app)

    response = client.post(
        "/api/portal/fault-scenarios/diagnose",
        json={
            "employeeId": "fault",
            "content": "CMDB 添加失败，怀疑 mysql 死锁",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "sessionId is required"


def test_fault_scenario_diagnose_route_rejects_non_matching_payload() -> None:
    client = TestClient(portal_backend.app)

    response = client.post(
        "/api/portal/fault-scenarios/diagnose",
        json={
            "sessionId": "fault-scenario-1",
            "employeeId": "fault",
            "content": "帮我看一下 Redis 命中率",
        },
    )

    assert response.status_code == 422
    assert "unsupported fault scenario" in response.json()["detail"]


def test_fault_scenario_diagnose_route_persists_history_with_unique_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    history_store: dict[str, list[dict]] = {"fault-scenario-1": []}

    monkeypatch.setattr(portal_backend.app.state, "multi_agent_manager", object(), raising=False)
    monkeypatch.setattr(
        portal_backend,
        "run_fault_scenario_diagnose",
        lambda payload: {
            "session": {
                "sessionId": payload["sessionId"],
                "scene": "cmdb_add_failed_mysql_deadlock",
            },
            "result": {
                "summary": "已定位为数据库死锁导致 CMDB 新增失败",
                "rootCause": {"type": "数据库异常"},
                "steps": [{"id": "database-analysis", "status": "success"}],
                "logEntries": [{"stage": "database-analysis", "summary": "锁等待命中"}],
            },
        },
    )

    async def fake_load_history(_request, *, session_id: str, user_id: str = "default") -> list[dict]:
        return list(history_store.get(session_id, []))

    async def fake_save_history(
        _request,
        *,
        session_id: str,
        messages: list[dict],
        user_id: str = "default",
    ) -> None:
        history_store[session_id] = list(messages)

    monkeypatch.setattr(portal_backend, "_load_portal_fault_history", fake_load_history)
    monkeypatch.setattr(portal_backend, "_save_portal_fault_history", fake_save_history)

    payload = {
        "sessionId": "fault-scenario-1",
        "employeeId": "fault",
        "content": "CMDB 添加失败，怀疑 mysql 死锁",
    }

    first_response = client.post("/api/portal/fault-scenarios/diagnose", json=payload)
    second_response = client.post("/api/portal/fault-scenarios/diagnose", json=payload)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert len(history_store["fault-scenario-1"]) == 4

    message_ids = [message["id"] for message in history_store["fault-scenario-1"]]
    assert len(message_ids) == len(set(message_ids))
    assert history_store["fault-scenario-1"][-1]["faultScenarioResult"]["rootCause"]["type"] == "数据库异常"


def test_fault_scenario_diagnose_route_shapes_partial_result_for_history_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    history_store: dict[str, list[dict]] = {"fault-scenario-1": []}

    monkeypatch.setattr(portal_backend.app.state, "multi_agent_manager", object(), raising=False)
    monkeypatch.setattr(
        portal_backend,
        "run_fault_scenario_diagnose",
        lambda payload: {
            "session": {
                "sessionId": payload["sessionId"],
                "scene": "cmdb_add_failed_mysql_deadlock",
            },
            "result": {
                "summary": "部分完成",
            },
        },
    )

    async def fake_load_history(_request, *, session_id: str, user_id: str = "default") -> list[dict]:
        return list(history_store.get(session_id, []))

    async def fake_save_history(
        _request,
        *,
        session_id: str,
        messages: list[dict],
        user_id: str = "default",
    ) -> None:
        history_store[session_id] = list(messages)

    monkeypatch.setattr(portal_backend, "_load_portal_fault_history", fake_load_history)
    monkeypatch.setattr(portal_backend, "_save_portal_fault_history", fake_save_history)

    response = client.post(
        "/api/portal/fault-scenarios/diagnose",
        json={
            "sessionId": "fault-scenario-1",
            "employeeId": "fault",
            "content": "CMDB 添加失败，怀疑 mysql 死锁",
        },
    )

    assert response.status_code == 200
    assert response.json()["result"]["steps"] == []
    assert response.json()["result"]["logEntries"] == []
    assert history_store["fault-scenario-1"][-1]["faultScenarioResult"]["steps"] == []
    assert history_store["fault-scenario-1"][-1]["faultScenarioResult"]["logEntries"] == []


def test_fault_disposal_history_normalizes_fault_scenario_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)

    async def fake_load_history(_request, *, session_id: str, user_id: str = "default") -> list[dict]:
        return [
            {
                "id": "agent-1",
                "type": "agent",
                "content": "部分完成",
                "faultScenarioResult": {
                    "summary": "部分完成",
                },
            }
        ]

    monkeypatch.setattr(portal_backend, "_load_portal_fault_history", fake_load_history)

    response = client.get("/api/portal/fault-disposal/history/fault-scenario-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][0]["faultScenarioResult"]["steps"] == []
    assert payload["messages"][0]["faultScenarioResult"]["logEntries"] == []


def test_fault_disposal_history_preserves_unknown_message_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)

    async def fake_load_history(_request, *, session_id: str, user_id: str = "default") -> list[dict]:
        return [
            {
                "id": "agent-1",
                "type": "agent",
                "content": "部分完成",
                "customField": {"source": "persisted"},
                "extraFlag": True,
                "faultScenarioResult": {
                    "summary": "部分完成",
                },
            }
        ]

    monkeypatch.setattr(portal_backend, "_load_portal_fault_history", fake_load_history)

    response = client.get("/api/portal/fault-disposal/history/fault-scenario-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][0]["customField"] == {"source": "persisted"}
    assert payload["messages"][0]["extraFlag"] is True
    assert payload["messages"][0]["faultScenarioResult"]["steps"] == []


def test_manual_workorder_dispatch_route_persists_record_and_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    history_store: dict[str, list[dict]] = {"chat-1": []}
    workorder_store: dict[str, dict[str, dict]] = {"chat-1": {}}

    async def fake_load_history(_request, *, session_id: str, user_id: str = "default") -> list[dict]:
        return list(history_store.get(session_id, []))

    async def fake_save_history(
        _request,
        *,
        session_id: str,
        messages: list[dict],
        user_id: str = "default",
    ) -> None:
        history_store[session_id] = list(messages)

    async def fake_load_workorders(_request, *, session_id: str, user_id: str = "default") -> dict[str, dict]:
        return dict(workorder_store.get(session_id, {}))

    async def fake_save_workorders(
        _request,
        *,
        session_id: str,
        records: dict[str, dict],
        user_id: str = "default",
    ) -> None:
        workorder_store[session_id] = dict(records)

    monkeypatch.setattr(portal_backend, "_load_portal_fault_history", fake_load_history)
    monkeypatch.setattr(portal_backend, "_save_portal_fault_history", fake_save_history)
    monkeypatch.setattr(portal_backend, "_load_portal_manual_workorders", fake_load_workorders)
    monkeypatch.setattr(portal_backend, "_save_portal_manual_workorders", fake_save_workorders)

    response = client.post(
        "/api/portal/fault-disposal/manual-workorders/dispatch",
        json={
            "chatId": "chat-1",
            "resId": "3094",
            "metricType": "mysql",
            "alarm": {
                "title": "数据库锁异常",
                "visibleContent": "数据库锁异常（db_mysql_001 10.43.150.186）",
                "deviceName": "db_mysql_001",
                "manageIp": "10.43.150.186",
            },
            "analysis": {
                "summary": "AI 无法直接止血，转人工处理",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending_manual"
    assert payload["dispatchRequest"]["chatId"] == "chat-1"
    assert payload["dispatchRequest"]["resId"] == "3094"
    assert payload["dispatchRequest"]["context"]["callback_url"].endswith(
        "/api/portal/fault-disposal/manual-workorders/notify-closed"
    )
    assert workorder_store["chat-1"]["3094"]["status"] == "pending_manual"
    assert history_store["chat-1"][-1]["manualWorkorder"]["resId"] == "3094"


def test_manual_workorder_close_notification_updates_history_and_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)
    history_store: dict[str, list[dict]] = {"chat-1": []}
    workorder_store: dict[str, dict[str, dict]] = {
        "chat-1": {
            "3094": {
                "chatId": "chat-1",
                "resId": "3094",
                "metricType": "mysql",
                "status": "pending_manual",
                "workorder": {"title": "数据库锁异常"},
            }
        }
    }

    async def fake_load_history(_request, *, session_id: str, user_id: str = "default") -> list[dict]:
        return list(history_store.get(session_id, []))

    async def fake_save_history(
        _request,
        *,
        session_id: str,
        messages: list[dict],
        user_id: str = "default",
    ) -> None:
        history_store[session_id] = list(messages)

    async def fake_load_workorders(_request, *, session_id: str, user_id: str = "default") -> dict[str, dict]:
        return dict(workorder_store.get(session_id, {}))

    async def fake_save_workorders(
        _request,
        *,
        session_id: str,
        records: dict[str, dict],
        user_id: str = "default",
    ) -> None:
        workorder_store[session_id] = dict(records)

    monkeypatch.setattr(portal_backend, "_load_portal_fault_history", fake_load_history)
    monkeypatch.setattr(portal_backend, "_save_portal_fault_history", fake_save_history)
    monkeypatch.setattr(portal_backend, "_load_portal_manual_workorders", fake_load_workorders)
    monkeypatch.setattr(portal_backend, "_save_portal_manual_workorders", fake_save_workorders)
    monkeypatch.setattr(
        portal_backend,
        "_run_alarm_metric_verification",
        lambda *, metric_type, res_id, max_metrics=5: {
            "definitions": {"source": "live"},
            "selectedMetrics": [
                {"code": "mysql_global_status_innodb_row_lock_time", "name": "InnoDB 总锁等待时长"}
            ],
            "metricDataResults": [
                {
                    "metricCode": "mysql_global_status_innodb_row_lock_time",
                    "latestValue": "0",
                    "avgValue": "0",
                    "source": "live",
                }
            ],
        },
    )

    response = client.post(
        "/api/portal/fault-disposal/manual-workorders/notify-closed",
        json={
            "chatId": "chat-1",
            "resId": "3094",
            "workorder": {
                "workorderNo": "WO-001",
                "status": "resolved",
                "handler": "alice",
            },
            "processing": {
                "summary": "已释放阻塞事务",
                "details": "人工终止长事务后恢复写入",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "recovered"
    assert payload["manualWorkorder"]["status"] == "manual_recovered"
    assert payload["verification"]["summary"] == "最新关键指标未见锁等待/慢 SQL 类异常，可初步判定已恢复"
    assert history_store["chat-1"][-1]["recoveryVerification"]["status"] == "recovered"


def test_manual_workorder_close_notification_returns_404_when_record_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)

    async def fake_load_workorders(_request, *, session_id: str, user_id: str = "default") -> dict[str, dict]:
        return {}

    monkeypatch.setattr(portal_backend, "_load_portal_manual_workorders", fake_load_workorders)

    response = client.post(
        "/api/portal/fault-disposal/manual-workorders/notify-closed",
        json={
            "chatId": "missing-chat",
            "resId": "3094",
            "processing": {"summary": "done"},
        },
    )

    assert response.status_code == 404
    assert "manual workorder not found" in response.json()["detail"]
