"""Exercise Portal chat ownership using the real chat routes and repository."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from qwenpaw.app.chats import api
from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.extensions.api import sso_settings_store
from qwenpaw.extensions.api.access_session import AccessIdentity, CURRENT_IDENTITY
from qwenpaw.extensions.api.chat_isolation import authorize_chat_payload, chat_scope


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("QWENPAW_TRUSTED_CHAT_ISOLATION", "true")
    monkeypatch.setattr(sso_settings_store, "get_userinfo_url", lambda: "https://test.invalid/userinfo")
    workspace = SimpleNamespace(
        chat_manager=ChatManager(repo=JsonChatRepository(tmp_path / "chats.json")),
        session=SafeJSONSession(save_dir=tmp_path / "sessions"),
        task_tracker=TaskTracker(),
    )
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_workspace] = lambda: workspace
    app.dependency_overrides[api.get_chat_manager] = lambda: workspace.chat_manager
    app.dependency_overrides[api.get_session] = lambda: workspace.session

    @app.middleware("http")
    async def inject_verified_test_principal(request: Request, call_next):
        name = request.headers.get("X-Verified-Test-User")
        identity = AccessIdentity({"userId": name}, "") if name else None
        token = CURRENT_IDENTITY.set(identity)
        try:
            return await call_next(request)
        finally:
            CURRENT_IDENTITY.reset(token)

    @app.post("/normalize-test")
    def normalize(payload: dict):
        authorize_chat_payload(payload, chat_scope())
        return payload

    with TestClient(app) as test_client:
        yield test_client


A = {"X-Verified-Test-User": "account-a"}
B = {"X-Verified-Test-User": "account-b"}


def create(client, who, chosen_owner="forged-owner", session="same-client-session"):
    result = client.post("/chats", headers=who, json={
        "name": "Private chat", "user_id": chosen_owner,
        "session_id": session, "channel": "console",
    })
    assert result.status_code == 200, result.text
    return result.json()


def test_object_ownership_applies_before_list_read_update_and_delete(client):
    assert client.get("/chats").status_code == 401
    alice = create(client, A)
    bob = create(client, B, chosen_owner=alice["user_id"])
    assert alice["user_id"] != bob["user_id"] != "forged-owner"
    assert alice["session_id"] != bob["session_id"]
    path = "/chats/" + alice["id"]
    assert client.get(path, headers=A).status_code == 200
    assert client.get(path, headers=B).status_code == 404
    assert client.put(path, headers=B, json={"name": "Changed"}).status_code == 404
    assert client.delete(path, headers=B).status_code == 404
    assert client.post("/chats/batch-delete", headers=B,
                       json=[bob["id"], alice["id"]]).status_code == 404
    assert client.get("/chats/" + bob["id"], headers=B).status_code == 200
    query = {"user_id": alice["user_id"]}
    assert [row["id"] for row in client.get("/chats", headers=B, params=query).json()] == [bob["id"]]
    assert client.put(path, headers=A, json={"name": "Changed"}).status_code == 200


def test_execution_and_reconnect_use_same_server_owned_namespace(client):
    alice = create(client, A)
    payload = {
        "channel_id": "console", "sender_id": "forged-owner", "meta": {
            "session_id": "same-client-session", "user_id": "forged-owner",
            "request_context": {"approval_level": "off", "root_session_id": "other"},
        },
    }
    normalized = client.post("/normalize-test", headers=A, json=payload).json()
    assert normalized["sender_id"] == normalized["meta"]["user_id"] == alice["user_id"]
    assert normalized["meta"]["session_id"] == alice["session_id"]
    assert normalized["meta"]["request_context"] == {"approval_level": "smart"}
    assert client.post("/normalize-test", headers=A, json=normalized).json() == normalized
    assert client.post("/normalize-test", headers=B, json=normalized).status_code == 404


def test_disabling_profile_keeps_scoped_chat_private(client, monkeypatch):
    alice = create(client, A)
    monkeypatch.setenv("QWENPAW_TRUSTED_CHAT_ISOLATION", "false")
    assert client.get("/chats").json() == []
    assert client.get("/chats/" + alice["id"]).status_code == 404
    assert client.post("/chats/batch-delete", json=[alice["id"]]).status_code == 404
    response = client.post("/chats", json={
        "user_id": "legacy", "session_id": alice["session_id"], "channel": "console",
    })
    assert response.status_code == 404


def test_raw_session_storage_is_unavailable_to_tools(client, monkeypatch, tmp_path):
    from qwenpaw.extensions.security import execution_policy

    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    for path in (
        tmp_path / "sessions" / "console" / "record.json",
        tmp_path / "ChAtS.JsOn.tmp",
        tmp_path / "chat_traces" / "trace.jsonl",
        tmp_path / "audit.db-wal",
    ):
        with pytest.raises(PermissionError):
            execution_policy.check_path(str(path))


def test_scheduled_collaboration_has_no_human_chat_scope(client):
    from fastapi import HTTPException
    from qwenpaw.extensions.api.collaboration_access import SOURCE

    def scope_for(identity):
        context = CURRENT_IDENTITY.set(identity)
        try:
            return chat_scope()
        finally:
            CURRENT_IDENTITY.reset(context)

    human = scope_for(AccessIdentity({"userId": "job-a"}, ""))
    job_a = scope_for(AccessIdentity({"job_id": "job-a"}, "", source=SOURCE))
    job_b = scope_for(AccessIdentity({"job_id": "job-b"}, "", source=SOURCE))
    assert len({human.owner, job_a.owner, job_b.owner}) == 3
    assert job_a.session_id("console") != job_b.session_id("console")
    with pytest.raises(HTTPException) as blocked:
        job_b.session_id(job_a.session_id("console"))
    assert blocked.value.status_code == 404
