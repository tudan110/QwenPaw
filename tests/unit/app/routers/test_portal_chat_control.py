"""Exercise actual async cancellation and persist only the observed results."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.portal_control import (
    PortalChatControl,
    PortalChatStopPending,
    PortalChatsPaused,
)
from qwenpaw.app.routers import console
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.extensions.api.access_policy import requires_admin
from qwenpaw.extensions.api.access_session import AccessIdentity, CURRENT_IDENTITY


_STOP = '"object": "portal_chat_stopped"'


async def test_batch_stops_24_chats_across_workspaces_including_disconnected(tmp_path):
    path = tmp_path / "control.json"
    control = PortalChatControl(path, timeout_seconds=30)
    trackers = [TaskTracker(), TaskTracker()]
    entered = 0
    cleaned = 0
    ready = asyncio.Event()

    async def blocked_dependency(_):
        nonlocal entered, cleaned
        entered += 1
        if entered == 24:
            ready.set()
        try:
            yield "data: first text\n\n"
            await asyncio.Future()
        finally:
            cleaned += 1

    streams = []
    for idx in range(24):
        tracker = trackers[idx % 2]
        key = f"chat-{idx}"
        queue, started = await control.start(tracker, key, None, blocked_dependency)
        assert started
        streams.append(tracker.stream_from_queue(queue, key))
    await asyncio.wait_for(ready.wait(), timeout=3)
    # Like a disconnected SSE client, one subscriber drops but the run stays.
    assert "first text" in await anext(streams[0])
    await streams[0].aclose()
    assert await trackers[0].get_status("chat-0") == "running"

    # A non-Portal task in the same tracker is out of scope.
    await trackers[0].register_external_task("external")
    result = await control.stop("admin")
    last = result["last_stop"]
    assert result["paused"] and last["counts"] == {"cancelled": 24}
    assert cleaned == 24
    assert await trackers[0].get_status("external") == "running"
    for stream in streams[1:]:
        events = [event async for event in stream]
        assert any(_STOP in e and '"cause": "admin"' in e for e in events)
    with pytest.raises(PortalChatsPaused):
        await control.start(trackers[0], "rejected", None, blocked_dependency)
    assert (await control.stop("admin"))["last_stop"]["id"] == last["id"]
    assert (await PortalChatControl(path, 30).status())["last_stop"] == last
    assert not (await control.reopen())["paused"]
    assert not (await PortalChatControl(path, 30).status())["paused"]
    await trackers[0].unregister_external_task("external")


async def test_waiting_for_cleanup_is_not_a_confirmed_stop(tmp_path):
    path = tmp_path / "control.json"
    control = PortalChatControl(path, 30)
    tracker = TaskTracker()
    release = asyncio.Event()

    async def slow_cleanup(_):
        try:
            yield "data: first text\n\n"
            await asyncio.Future()
        finally:
            await release.wait()

    queue, _ = await control.start(tracker, "slow", None, slow_cleanup)
    stream = tracker.stream_from_queue(queue, "slow")
    assert "first text" in await anext(stream)
    try:
        result = await control.stop("admin")
        assert result["last_stop"]["counts"] == {"accepted": 1}
        with pytest.raises(PortalChatStopPending):
            await control.reopen()
        # With a new coordinator (no former process's handles), the old
        # cancellation cannot be confirmed. A freeze still survives restart.
        restart_path = tmp_path / "restarted.json"
        restart_path.write_bytes(path.read_bytes())
        restarted = await PortalChatControl(restart_path, 30).status()
        assert restarted["paused"]
        assert restarted["last_stop"]["counts"] == {"unknown": 1}
    finally:
        release.set()
    assert '"cause": "admin"' in await asyncio.wait_for(anext(stream), timeout=2)
    await stream.aclose()
    assert (await control.status())["last_stop"]["counts"] == {"cancelled": 1}
    assert not (await control.reopen())["paused"]


async def test_local_timeout_runs_without_an_admin_request(tmp_path):
    control = PortalChatControl(tmp_path / "control.json", 0.02)
    tracker = TaskTracker()
    closed = asyncio.Event()

    async def blocked_dependency(_):
        try:
            yield "data: first text\n\n"
            await asyncio.Future()
        finally:
            closed.set()

    queue, _ = await control.start(tracker, "slow-model", None, blocked_dependency)
    stream = tracker.stream_from_queue(queue, "slow-model")
    assert "first text" in await anext(stream)
    assert '"cause": "timeout"' in await asyncio.wait_for(anext(stream), timeout=2)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert closed.is_set() and await tracker.get_status("slow-model") == "idle"
    assert not (await control.status())["paused"]


async def test_admin_endpoint_controls_normal_console_route(tmp_path, monkeypatch):
    monkeypatch.setenv("QWENPAW_TRUSTED_CHAT_ISOLATION", "true")
    monkeypatch.setenv("QWENPAW_TRUSTED_CHAT_TEXT_GUARD", "false")
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "admin")
    tracker = TaskTracker()
    ready = asyncio.Event()
    chats = {}

    async def stream_one(_):
        ready.set()
        yield "data: first text\n\n"
        await asyncio.Future()

    async def find_or_create(session_id, owner, channel, **_):
        chat = ChatSpec(id="chat", name="sample", session_id=session_id, user_id=owner, channel=channel)
        chats[chat.id] = chat
        return chat

    channel = SimpleNamespace(stream_one=stream_one, resolve_session_id=lambda **kw: kw["channel_meta"]["session_id"])
    workspace = SimpleNamespace(
        agent_id="gateway",
        channel_manager=SimpleNamespace(get_channel=AsyncMock(return_value=channel)),
        task_tracker=tracker,
        chat_manager=SimpleNamespace(get_or_create_chat=find_or_create, get_chat=AsyncMock(side_effect=chats.get)),
    )
    monkeypatch.setattr(console, "get_agent_for_request", AsyncMock(return_value=workspace))
    app = FastAPI()
    app.state.portal_chat_control = PortalChatControl(tmp_path / "control.json", 30)
    app.include_router(console.router)

    @app.middleware("http")
    async def identity(request, call_next):
        user = request.headers.get("X-Test-User")
        token = CURRENT_IDENTITY.set(AccessIdentity({"userId": user}, "") if user else None)
        try:
            return await call_next(request)
        finally:
            CURRENT_IDENTITY.reset(token)

    user, admin = {"X-Test-User": "alice"}, {"X-Test-User": "admin"}
    body = {"session_id": "sample", "input": [{"role": "user", "content": [{"type": "text", "text": "long reply"}]}]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        ctl = "/console/chat/control"
        assert (await client.get(ctl)).status_code == 401
        assert (await client.get(ctl, headers=user)).status_code == 403
        assert (await client.post(ctl, json={"paused": True}, headers=user)).status_code == 403
        denied = await client.post(ctl, json={"paused": True}, headers={**admin, "Origin": "https://untrusted.invalid"})
        assert denied.status_code == 403
        run = asyncio.create_task(client.post("/console/chat", json=body, headers=user))
        await asyncio.wait_for(ready.wait(), timeout=3)
        response = await client.post(ctl, json={"paused": True}, headers=admin)
        assert response.json()["last_stop"]["counts"] == {"cancelled": 1}
        assert _STOP in (await asyncio.wait_for(run, timeout=3)).text
        assert (await client.post("/console/chat", json=body, headers=user)).status_code == 503
        continuation = {"chat_id": "chat", "question": "long reply", "draft": "first text"}
        assert (await client.post("/console/chat/continue", json=continuation, headers=user)).status_code == 503
        assert not (await client.post(ctl, json={"paused": False}, headers=admin)).json()["paused"]
    assert requires_admin("GET", "/api/console/chat/control")
    assert requires_admin("POST", "/api/agents/gateway/console/chat/control")
    persisted = json.loads((tmp_path / "control.json").read_text())
    assert persisted["last_stop"]["tasks"][0]["status"] == "cancelled"
