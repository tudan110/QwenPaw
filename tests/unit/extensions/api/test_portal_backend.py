# -*- coding: utf-8 -*-
"""Tests for portal employee runtime status aggregation."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

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
