"""Exercise controlled business operations through the real Portal access policy."""

from concurrent.futures import ThreadPoolExecutor
import time
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from qwenpaw.app.routers import controlled_documents as api
from qwenpaw.app.routers.console import router as console_router
from qwenpaw.extensions.api import controlled_documents as store
from qwenpaw.extensions.api import sso_settings_store
from qwenpaw.extensions.api.sso_token_middleware import SsoTokenMiddleware

BASE = "/api/portal/controlled-documents"
A = {"X-Inoe-Token": "owner"}
B = {"X-Inoe-Token": "viewer"}
ADMIN = {"X-Inoe-Token": "reviewer"}
SECRET = "password: example-control-check-123"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STORE_DIR", tmp_path / "secret")
    monkeypatch.setenv("QWENPAW_CONTROLLED_DOCUMENTS", "true")
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "true")
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "reviewer,reviewer2")
    monkeypatch.setenv("QWENPAW_BROWSER_ORIGINS", "http://testserver")
    realm = lambda: "https://example.invalid/userinfo"
    monkeypatch.setattr(api, "get_userinfo_url", realm)
    monkeypatch.setattr(sso_settings_store, "get_userinfo_url", realm)

    async def validate(token, url, *, use_cache):
        if token not in {"owner", "viewer", "reviewer", "reviewer2"}:
            raise HTTPException(401)
        return {"userId": token}

    application = FastAPI()
    application.add_middleware(SsoTokenMiddleware, validator=AsyncMock(validate=AsyncMock(side_effect=validate)))
    application.include_router(api.router, prefix="/api")
    application.include_router(console_router, prefix="/api")
    with TestClient(application, base_url="http://testserver", headers={"Origin": "http://testserver"}) as client:
        yield client


def post(client, path, headers=A, status=200, **body):
    response = client.post(BASE + path, headers=headers, json=body or None)
    assert response.status_code == status, response.text
    return response


def get(client, path, headers=A, status=200):
    response = client.get(BASE + path, headers=headers)
    assert response.status_code == status, response.text
    return response.json()


def create(client, content=SECRET, owner=A):
    return post(client, "/documents", owner, 201, title="测试资料", content=content).json()["id"]


def operation(client, kind, targets, owner=A, **extra):
    return post(client, "/operations", owner, 201, kind=kind, targets=targets, **extra).json()["id"]


def approve(client, identifier, owner=A):
    assert post(client, f"/operations/{identifier}/confirm", owner).json()["status"] == "pending_review"
    post(client, f"/operations/{identifier}/execute", owner, 403)
    post(client, f"/admin/review/{identifier}", ADMIN, approve=True)


def test_auth_owner_and_sensitive_export(client, monkeypatch):
    get(client, "/state", {}, 401)
    identifier = create(client)
    path = f"/documents/{identifier}"
    assert get(client, "/state", B)["documents"] == []
    get(client, path, ADMIN, 404)  # Admin cannot read other users' originals.
    assert get(client, path)["content"] == "[凭据已遮蔽]"
    post(client, "/operations", B, 404, kind="export", targets=[identifier])
    op = operation(client, "export", [identifier])
    post(client, f"/operations/{op}/download", A, 403)
    approve(client, op)
    post(client, f"/operations/{op}/execute")
    response = post(client, f"/operations/{op}/download")
    assert response.text == SECRET and response.headers["cache-control"] == "no-store"
    post(client, f"/operations/{op}/download", A, 403)
    state = get(client, "/admin/state", ADMIN)
    assert any(item["action"] == "export.download" and item["result"] == "success" for item in state["events"])
    assert SECRET not in str(state)
    get(client, "/admin/state", A, 403)
    response = client.post(BASE + "/documents", headers={**A, "Origin": "https://foreign.invalid"}, json={"title": "x", "content": "y"})
    assert response.status_code == 403
    monkeypatch.setattr(api, "get_userinfo_url", lambda: "https://other.invalid/userinfo")
    assert not get(client, "/admin/state", ADMIN)["events"]
    get(client, path, A, 404)


def test_shared_preview_expires_and_is_revocable(client):
    identifier = create(client)
    path = f"/documents/{identifier}"
    get(client, path, B, 404)
    op = operation(client, "share", [identifier], recipient="viewer", minutes=1)
    approve(client, op)
    post(client, f"/operations/{op}/execute")
    assert get(client, path, B)["masked"]
    post(client, "/operations", B, 404, kind="export", targets=[identifier])
    grant = get(client, "/state")["grants"][0]["id"]
    post(client, f"/grants/{grant}/revoke", B, 404)
    post(client, f"/grants/{grant}/revoke")
    get(client, path, B, 404)
    op = operation(client, "share", [identifier], recipient="viewer", minutes=1)
    approve(client, op)
    post(client, f"/operations/{op}/execute")
    actor = store.Actor(api.get_userinfo_url(), "owner")
    with store.connection(actor) as db:
        db.execute("UPDATE grants SET expires=?", (time.time() - 1,))
    get(client, path, B, 404)
    assert get(client, "/state", B)["documents"] == []


def test_admin_cannot_review_own_request(client):
    identifier = create(client, owner=ADMIN)
    op = operation(client, "export", [identifier], ADMIN)
    post(client, f"/operations/{op}/confirm", ADMIN)
    post(client, f"/admin/review/{op}", ADMIN, 403, approve=True)
    response = post(client, f"/admin/review/{op}", {"X-Inoe-Token": "reviewer2"}, approve=False)
    assert response.json()["status"] == "rejected"
    post(client, f"/operations/{op}/execute", ADMIN, 409)


def wait_cursor(client, op, minimum):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = next(row for row in get(client, "/state")["operations"] if row["id"] == op)
        if result["cursor"] >= minimum:
            return result
        time.sleep(0.025)
    pytest.fail("No durable progress from the live archive worker")


def test_live_batch_pause_resume_shutdown_and_rollback(client):
    ids = [create(client, f"normal {i}") for i in range(4)]
    op = operation(client, "archive", ids)
    approve(client, op)
    with ThreadPoolExecutor(max_workers=1) as executor:
        starting = executor.submit(post, client, f"/operations/{op}/execute")
        wait_cursor(client, op, 1)
        paused = post(client, f"/operations/{op}/control/pause").json()
        assert paused["status"] == "paused" and 1 <= paused["cursor"] < len(ids)
        starting.result(timeout=7)
        documents = get(client, "/state")["documents"]
        assert sum(doc["archived"] for doc in documents) == paused["cursor"]
        resumed = executor.submit(post, client, f"/operations/{op}/control/resume")
        wait_cursor(client, op, paused["cursor"] + 1)
        assert post(client, "/admin/emergency", ADMIN, active=True).json()["affected"] == 1
        resumed.result(timeout=7)
        frozen = next(row for row in get(client, "/state")["operations"] if row["id"] == op)
        assert frozen["status"] == "paused" and frozen["cursor"] < len(ids)
        post(client, f"/operations/{op}/control/resume", A, 423)
        post(client, "/operations", A, 423, kind="archive", targets=ids[:1])
        post(client, "/admin/emergency", ADMIN, active=False)
        post(client, f"/operations/{op}/control/resume")
    assert all(doc["archived"] for doc in get(client, "/state")["documents"])
    post(client, f"/operations/{op}/control/rollback")
    assert all(not doc["archived"] for doc in get(client, "/state")["documents"])
    assert get(client, f"/documents/{ids[-1]}")["content"] == "normal 3"


def test_threshold_rejection_alert_and_policy_restore(client):
    ids = [create(client, f"normal {i}") for i in range(3)]
    post(client, "/admin/policy", ADMIN, batch_cap=2, alert_limit=2)
    deny = post(client, "/operations", A, 422, kind="archive", targets=ids).json()
    assert "分成多批" in deny["detail"]
    for _ in range(2):
        get(client, f"/documents/{ids[0]}", B, 404)
    state = get(client, "/admin/state", ADMIN)
    assert len(state["incidents"]) == 1
    assert get(client, "/state", B)["security_hold"]
    post(client, "/operations", B, 423, kind="archive", targets=ids[:1])
    incident = state["incidents"][0]
    assert incident["threshold"] == 2 and incident["subject"] == "viewer"
    assert any(row["id"] == incident["event_id"] and row["result"] == "blocked" for row in state["events"])
    post(client, f"/admin/incidents/{incident['id']}/resolve", ADMIN)
    assert not get(client, "/state", B)["security_hold"]
    revision = state["revisions"][0]
    restored = post(client, f"/admin/policy/{revision['id']}/restore", ADMIN).json()
    assert restored["batch_cap"] == 10 and restored["alert_limit"] == 3
    assert get(client, "/admin/state", ADMIN)["incidents"][0]["resolved"]
    operation(client, "archive", ids)


def test_text_only_portal_sample_rejects_attachment_upload(client, monkeypatch):
    monkeypatch.setenv("QWENPAW_TRUSTED_CHAT_TEXT_GUARD", "true")
    monkeypatch.setenv("QWENPAW_TRUSTED_CHAT_ISOLATION", "true")
    response = client.post("/api/console/upload", headers=A, files={"file": ("sample.txt", b"sample")})
    assert response.status_code == 415
    assert "unsupported-media" in response.json()["detail"]
