"""Stopped Portal history and bounded CMDB retry, across the HTTP boundary."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from agentscope.message import Msg, TextBlock
from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.state import AgentState
from fastapi import FastAPI

from qwenpaw.agents import model_factory
from qwenpaw.app.chats import api, cmdb_retry
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.portal_control import PortalChatControl
from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.app.routers import console
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.extensions.api.access_session import AccessIdentity, CURRENT_IDENTITY
from qwenpaw.extensions.api.chat_isolation import PortalChatScope
from qwenpaw.extensions.integrations.zgops_cmdb import portal_asset_lookup
from qwenpaw.runtime._state_utils import StateProxy

ASSET = "TESTZG-BJ-BJ-WLKJC-A-1.MCN.MX.ATN980C"
QUERY = "查询CMDB 查询资产 " + ASSET
DRAFT = "我来为您查询这个 CMDB 资产信息。"


@pytest.fixture
def portal(monkeypatch, tmp_path):
    scope = {"value": PortalChatScope("a" * 32)}
    chat = ChatSpec(id="chat-a", session_id=scope["value"].session_id("session-a"),
                    user_id=scope["value"].owner, channel="console")
    workspace = SimpleNamespace(
        agent_id="gateway", workspace_dir=str(tmp_path), task_tracker=TaskTracker(),
        session=SafeJSONSession(str(tmp_path / "sessions")),
        chat_manager=SimpleNamespace(get_chat=AsyncMock(return_value=chat),
                                     get_or_create_chat=AsyncMock(return_value=chat)),
    )
    monkeypatch.setenv("QWENPAW_TRUSTED_CHAT_ISOLATION", "true")
    monkeypatch.setenv("QWENPAW_TRUSTED_CHAT_TEXT_GUARD", "false")
    monkeypatch.setenv("INOE_API_BASE_URL", "https://cmdb.test")
    monkeypatch.setattr(console, "chat_scope", lambda: scope["value"])
    monkeypatch.setattr(api, "chat_scope", lambda: scope["value"])
    monkeypatch.setattr(console, "get_agent_for_request", AsyncMock(return_value=workspace))
    monkeypatch.setattr(console, "generate_and_update_title", AsyncMock())
    monkeypatch.setattr(cmdb_retry, "resolve_effective_skills", lambda *_: ["zgops-cmdb"])
    app = FastAPI()
    app.dependency_overrides[api.get_workspace] = lambda: workspace
    app.dependency_overrides[api.get_chat_manager] = lambda: workspace.chat_manager
    app.dependency_overrides[api.get_session] = lambda: workspace.session
    app.state.portal_chat_control = PortalChatControl(tmp_path / "control.json", 30)
    app.include_router(console.router)
    app.include_router(api.router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test"), workspace, chat, scope


def sse(event):
    return "data: " + json.dumps(event) + "\n\n"


def history_text(history):
    return [(msg["role"], "".join(p["text"] for p in msg["content"])) for msg in history["messages"]]


async def stop_query(client, workspace, question, *, tool):
    waiting = asyncio.Event()

    async def stream(_payload):
        yield sse({"object": "message", "id": "reply", "role": "assistant", "type": "message"})
        yield sse({"object": "content", "msg_id": "reply", "type": "text", "delta": True, "text": DRAFT})
        yield sse({"object": "message", "id": "private", "role": "assistant", "type": "reasoning"})
        yield sse({"object": "content", "msg_id": "private", "type": "text", "text": "hidden detail"})
        if tool:
            yield sse({"object": "message", "id": "tool", "type": "plugin_call",
                       "content": [{"type": "data", "data": {"arguments": "private tool data"}}]})
        waiting.set()
        await asyncio.Future()

    workspace.channel_manager = SimpleNamespace(get_channel=AsyncMock(return_value=SimpleNamespace(
        stream_one=stream, resolve_session_id=lambda **kw: kw["channel_meta"]["session_id"],
    )))
    stream_response = asyncio.create_task(client.post("/console/chat", json={
        "session_id": "session-a", "input": [{"role": "user", "type": "message", "content": [
            {"type": "text", "text": question},
        ]}],
    }))
    try:
        await asyncio.wait_for(waiting.wait(), 5)
        stop = await client.post("/console/chat/stop", params={"chat_id": "chat-a"})
        assert stop.status_code == 200
        assert stop.json()["status"] == "cancelled"
        await asyncio.wait_for(stream_response, 5)
        return stop.json()["checkpoint"]
    finally:
        if not stream_response.done():
            stream_response.cancel()


async def test_stopped_cmdb_reopens_and_retries_as_original_owner(portal, monkeypatch):
    client, workspace, chat, scope = portal
    http_client = httpx.AsyncClient
    upstream_tokens = []

    def upstream(request):
        assert request.method == "GET" and request.url.params["q"] == f"name:{ASSET}"
        upstream_tokens.append(request.headers["Authorization"])
        return httpx.Response(200, json={"result": [{"name": ASSET, "_id": "cmdb-asset-id"}]})

    monkeypatch.setattr(portal_asset_lookup.httpx, "AsyncClient", lambda **kwargs: http_client(
        **kwargs, transport=httpx.MockTransport(upstream),
    ))
    monkeypatch.setattr(cmdb_retry.AgentBuilder, "_init_governor", lambda *_: None)
    calls = []
    original_wrap = cmdb_retry.AgentBuilder._wrap_tool

    def wrap(fn, agent, context, governor):
        calls.append(context)
        tool = original_wrap(fn, agent, context, governor)
        tool.check_permissions = AsyncMock(return_value=PermissionDecision(PermissionBehavior.ALLOW, "test"))
        return tool

    monkeypatch.setattr(cmdb_retry.AgentBuilder, "_wrap_tool", wrap)
    identity = CURRENT_IDENTITY.set(AccessIdentity({"userId": "test-user"}, "caller-token"))
    try:
        async with client:
            marker = await stop_query(client, workspace, QUERY, tool=True)
            assert marker["mode"] == "cmdb"
            # Load a fresh session instance to ensure history does not depend on in-memory state.
            workspace.session = SafeJSONSession(workspace.session.save_dir)
            history = (await client.get("/chats/chat-a")).json()
            assert history["stopped_turn"] == marker
            assert history_text(history) == [("user", QUERY), ("assistant", DRAFT)]
            params = {"chat_id": chat.id, "turn_id": marker["id"], "approval_level": "strict"}
            owner = scope["value"]
            scope["value"] = PortalChatScope("b" * 32)
            assert (await client.get("/chats/chat-a")).status_code == 404
            assert (await client.post("/console/chat/retry-cmdb", json=params)).status_code == 404
            assert upstream_tokens == []
            scope["value"] = owner
            response = await client.post("/console/chat/retry-cmdb", json=params)
            assert "portal_cmdb_retry" in response.text and "cmdb-asset-id" in response.text
            assert upstream_tokens == ["Bearer caller-token"]
            assert calls[0]["approval_level"] == "strict"
            history = (await client.get("/chats/chat-a")).json()
            assert history["stopped_turn"] is None
            assert len(history["messages"]) == 2 and "cmdb-asset-id" in history_text(history)[-1][1]
            await client.post("/console/chat/retry-cmdb", json=params)
            assert upstream_tokens == ["Bearer caller-token"]
    finally:
        CURRENT_IDENTITY.reset(identity)


async def test_stopped_non_cmdb_tool_keeps_history_without_retry(portal, monkeypatch):
    client, workspace, _, _ = portal
    lookup = AsyncMock()
    monkeypatch.setattr(console, "retry_cmdb_lookup", lookup)
    question = "运行需要审批的操作"
    async with client:
        marker = await stop_query(client, workspace, question, tool=True)
        assert marker["mode"] == "none"
        history = (await client.get("/chats/chat-a")).json()
        assert history_text(history) == [("user", question), ("assistant", DRAFT)]
        response = await client.post("/console/chat/retry-cmdb", json={"chat_id": "chat-a", "turn_id": marker["id"]})
        assert "portal_cmdb_retry" not in response.text
        lookup.assert_not_awaited()


async def test_text_continuation_updates_history_using_server_draft(portal, monkeypatch):
    client, workspace, chat, _ = portal
    earlier = StateProxy()
    earlier.data = {"state": AgentState(context=[
        Msg(name="user", role="user", content=[TextBlock(text="早先的提问")]),
        Msg(name="assistant", role="assistant", content=[TextBlock(text="早先的回复")]),
    ]).model_dump(mode="json")}
    await workspace.session.save_session_state(chat.session_id, chat.user_id, chat.channel, agent=earlier)

    async def model(messages):
        assert json.loads(messages[-1].content[0].text) == {"question": "续写测试", "draft": DRAFT}
        return {"content": [{"type": "text", "text": "继续的正文。"}]}

    monkeypatch.setattr(model_factory, "create_model_and_formatter", lambda **_: (model, None))
    async with client:
        marker = await stop_query(client, workspace, "续写测试", tool=False)
        assert marker["mode"] == "text"
        response = await client.post("/console/chat/continue", json={
            "chat_id": chat.id, "turn_id": marker["id"], "question": "浏览器副本", "draft": "浏览器草稿",
        })
        assert response.status_code == 200 and '"status": "completed"' in response.text
        history = (await client.get("/chats/chat-a")).json()
        assert history_text(history) == [
            ("user", "早先的提问"), ("assistant", "早先的回复"),
            ("user", "续写测试"), ("assistant", DRAFT + "继续的正文。"),
        ]
        assert history["stopped_turn"] is None


async def test_model_only_query_does_not_dispatch_agent_or_business_tools(portal, monkeypatch):
    client, workspace, chat, scope = portal
    business_stream = AsyncMock(side_effect=AssertionError("must not dispatch the agent"))
    workspace.channel_manager = SimpleNamespace(get_channel=AsyncMock(return_value=SimpleNamespace(
        stream_one=business_stream, resolve_session_id=lambda **kw: kw["channel_meta"]["session_id"],
    )))
    model_calls = []

    async def model(messages, **kwargs):
        model_calls.append(messages[-1].get_text_content())
        assert kwargs == {}  # No tool declarations or callbacks go to the model.
        return {"content": [{"type": "text", "text": "业务联网已关闭，本轮未查询 CMDB。"}]}

    monkeypatch.setattr(model_factory, "create_model_and_formatter", lambda **_: (model, None))
    payload = {"session_id": "session-a", "input": [{"role": "user", "type": "message", "content": [
        {"type": "text", "text": QUERY},
    ]}]}
    async with client:
        owner = scope["value"]
        scope["value"] = None
        assert (await client.post("/console/chat/model-only", json=payload)).status_code == 503
        scope["value"] = owner
        result = await client.post("/console/chat/model-only", json=payload)
        assert result.status_code == 200 and '"portal_model_only": true' in result.text
        assert model_calls == [QUERY]
        business_stream.assert_not_called()
        history = (await client.get(f"/chats/{chat.id}")).json()
        assert history_text(history) == [("user", QUERY), ("assistant", "业务联网已关闭，本轮未查询 CMDB。")]
