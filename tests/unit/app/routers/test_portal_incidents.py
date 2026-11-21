"""Exercise the Portal incident control against live local task handles."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.app.chats.portal_control import (
    PortalChatControl,
    PortalChatStopPending,
    PortalChatsPaused,
    PortalIncidentReviewRequired,
)
from qwenpaw.app.routers import console
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.extensions.api.access_policy import requires_admin
from qwenpaw.extensions.api.access_session import AccessIdentity, CURRENT_IDENTITY


BASE = "/console/chat/control/incidents"


async def test_risk_stop_withholds_queued_output_and_records_checkpoint(tmp_path):
    path = tmp_path / "control.json"
    control = PortalChatControl(path, 30)
    tracker = TaskTracker()
    ready = asyncio.Event()
    snapshots = []

    async def stream(_):
        yield "pending-content"
        ready.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            # A provider can ignore a cancellation once, which must not
            # allow it to send additional output after the incident stop.
            yield "late-content"

    async def checkpoint(events):
        snapshots.extend(events)
        return {"id": "turn-a", "raw": "private-state"}

    queue, _ = await control.start(
        tracker, "chat-a", None, stream,
        portal_turn=("agent-a", "turn-a"), on_stop=checkpoint,
    )
    await asyncio.wait_for(ready.wait(), timeout=3)
    assert (await control.incidents(1))["active_count"] == 1
    state = await control.stop("admin", "data_exposure")
    batch = state["last_stop"]["id"]
    assert state["last_stop"]["counts"] == {"cancelled": 1}
    events = [event async for event in tracker.stream_from_queue(queue, "chat-a")]
    assert any("portal_chat_stopped" in event for event in events)
    assert "pending-content" not in "".join(events)
    assert "late-content" not in "".join(events)
    assert "private-state" not in "".join(events)
    assert snapshots == ["pending-content"]

    with pytest.raises(PortalChatsPaused):
        await control.start(tracker, "another-chat", None, stream)
    with pytest.raises(PortalIncidentReviewRequired):
        await control.reopen("admin")
    with pytest.raises(PortalIncidentReviewRequired):
        await control.rollback("admin", batch, None)

    restarted = PortalChatControl(path, 30)
    view = await restarted.incidents(1)
    assert view["paused"] and view["active_count"] == 0
    assert view["latest"]["reason"] == "data_exposure"
    details = await restarted.incident(batch, 1)
    assert details["tasks"][0]["checkpoint_saved"] is True
    assert details["tasks"][0]["chat_id"] == "chat-a"
    assert details["tasks"][0]["turn_id"] == "turn-a"
    assert details["tasks"][0]["finished_at"] >= details["tasks"][0]["started_at"]
    assert not any(secret in path.read_text() for secret in ("private-state", "pending-content", "late-content"))
    await restarted.reopen("reviewer", reviewed_batch=batch)
    await restarted.stop("another-admin", "unauthorized_network")
    history = await PortalChatControl(path, 30).incidents(1)
    old = history["records"][1]
    assert old["id"] == batch and old["resume"]["actor"] == "reviewer"
    assert history["total"] == 2 and history["latest"]["reason"] == "unauthorized_network"
    assert (await restarted.incident(batch, 1))["tasks"][0]["checkpoint_saved"] is True


async def test_pending_cleanup_does_not_become_stop_success(tmp_path):
    control = PortalChatControl(tmp_path / "pending.json", 30)
    tracker = TaskTracker()
    ready = asyncio.Event()
    release = asyncio.Event()

    async def stream(_):
        try:
            yield "first"
            ready.set()
            await asyncio.Future()
        finally:
            await release.wait()

    queue, _ = await control.start(tracker, "chat", None, stream)
    await asyncio.wait_for(ready.wait(), timeout=3)
    try:
        stopped = await control.stop("admin", "unauthorized_execution")
        batch = stopped["last_stop"]["id"]
        assert stopped["last_stop"]["counts"] == {"accepted": 1}
        assert (await control.incident(batch, 1))["tasks"][0]["checkpoint_saved"] is None
        with pytest.raises(PortalChatStopPending):
            await control.reopen("admin", reviewed_batch=batch)
        after_restart = await PortalChatControl(control.path, 30).incidents(1)
        assert after_restart["latest"]["counts"] == {"unknown": 1}
    finally:
        release.set()
        async with asyncio.timeout(3):
            async for _ in tracker.stream_from_queue(queue, "chat"):
                pass
    assert (await control.incidents(1))["latest"]["counts"] == {"cancelled": 1}


async def test_interrupted_stop_is_not_overwritten_as_empty_success(tmp_path):
    path = tmp_path / "control.json"
    interrupted = {"id": "a" * 32, "at": 1.0, "actor": "admin", "reason": "data_exposure", "tasks": None, "elapsed_ms": None}
    path.write_text(json.dumps({"last_stop": interrupted, "paused": True}))
    control = PortalChatControl(path, 30)
    repeated = await control.stop("admin", "data_exposure")
    assert repeated["last_stop"]["id"] == interrupted["id"]
    assert repeated["last_stop"]["total"] is None
    assert (await control.incidents(1))["total"] == 1


async def test_incident_endpoints_require_admin_origin_and_current_batch(monkeypatch, tmp_path):
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "admin")
    monkeypatch.setenv("QWENPAW_TRUSTED_CHAT_ISOLATION", "true")
    app = FastAPI()
    app.state.portal_chat_control = PortalChatControl(tmp_path / "routes.json", 30)
    app.include_router(console.router)

    @app.middleware("http")
    async def test_identity(request, call_next):
        actor = request.headers.get("X-Test-Actor")
        token = CURRENT_IDENTITY.set(AccessIdentity({"userId": actor}, "") if actor else None)
        try:
            return await call_next(request)
        finally:
            CURRENT_IDENTITY.reset(token)

    admin = {"X-Test-Actor": "admin"}
    user = {"X-Test-Actor": "user"}
    reason = {"reason": "data_exposure"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal") as client:
        assert (await client.get(BASE)).status_code == 401
        assert (await client.get(BASE, headers=user)).status_code == 403
        assert (await client.get(BASE + "/" + "a" * 32, headers=user)).status_code == 403
        assert (await client.post(BASE + "/stop", headers=user, json=reason)).status_code == 403
        assert (await client.post(BASE + "/stop", headers={**admin, "Origin": "http://untrusted"}, json=reason)).status_code == 403
        assert (await client.post(BASE + "/stop", headers=admin, json={**reason, "actor": "user"})).status_code == 422
        response = await client.post(BASE + "/stop", headers=admin, json=reason)
        assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
        latest = response.json()["latest"]
        assert latest["total"] == 0 and latest["actor"] == "admin"
        assert (await client.post("/console/chat/control", headers=admin, json={"paused": False})).status_code == 409
        assert (await client.post(BASE + "/resume", headers=admin, json={"batch_id": latest["id"]})).status_code == 422
        assert (await client.post(BASE + "/resume", headers=admin, json={"batch_id": "b" * 32, "confirm": "确认复核并恢复"})).status_code == 409
        resumed = await client.post(BASE + "/resume", headers=admin, json={"batch_id": latest["id"], "confirm": "确认复核并恢复"})
        assert resumed.status_code == 200 and not resumed.json()["paused"]
        detail = await client.get(f"{BASE}/{latest['id']}", headers=admin)
        assert detail.json()["batch"]["resume"]["actor"] == "admin"
        monkeypatch.setenv("QWENPAW_TRUSTED_CHAT_ISOLATION", "false")
        assert (await client.get(BASE, headers=admin)).json() == {"enabled": False}
        assert (await client.post(BASE + "/stop", headers=admin, json=reason)).status_code == 404
    assert requires_admin("GET", f"/api{BASE}")
    assert requires_admin("POST", f"/api/agents/gateway{BASE}/resume")
