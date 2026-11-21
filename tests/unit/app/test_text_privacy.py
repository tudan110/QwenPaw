"""Text privacy policies are persisted and used before dispatch, not UI flags."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.app.routers import console
from qwenpaw.extensions.api import controlled_documents as store, text_privacy as privacy
from qwenpaw.governance import component_events
from qwenpaw.providers.retry_chat_model import RetryChatModel


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STORE_DIR", tmp_path / "private")
    monkeypatch.setattr(component_events, "WORKING_DIR", tmp_path / "work")


@pytest.mark.asyncio
async def test_scope_and_persistence_without_raw_values():
    sample = "合同编号：DEMO-CONTRACT-NOT-REAL"
    assert privacy.status()["policy"]["chat_input"] == "off"
    await privacy.check("chat_input", [sample])
    assert not store.STORE_DIR.exists()

    privacy.save(privacy.PrivacyPolicy(
        builtin=[], custom_fields=["合同编号"], chat_input="observe", model_context="block",
    ), "inoe:admin")
    await privacy.check("chat_input", ["合同", "编号：DEMO-CONTRACT-NOT-REAL"])
    await privacy.check("chat_input", ["合规编号：DEMO-CONTRACT-NOT-REAL", "19900000000"])
    with pytest.raises(privacy.PrivacyBlocked, match="模型上下文") as error:
        await privacy.check("model_context", [{"role": "tool", "content": {"合同编号": "DEMO-CONTRACT-NOT-REAL"}}])
    assert "DEMO-CONTRACT" not in str(error.value)
    status = privacy.status()
    assert status["policy"]["revision"] == 1
    assert status["policy"]["custom_fields"] == ["合同编号"]
    assert [(hit["scene"], hit["decision"], hit["rule_count"]) for hit in status["hits"]] == [
        ("model_context", "blocked", 1), ("chat_input", "observed", 1),
    ]
    assert "DEMO-CONTRACT" not in str(status)
    changes = component_events.list_changes(supply=False, limit=10, offset=0)["records"]
    assert [change["kind"] for change in changes] == ["privacy_policy"]
    assert "合同编号" not in str(changes)
    assert b"DEMO-CONTRACT" not in (store.STORE_DIR / "privacy-policy.sqlite3").read_bytes()

    with pytest.raises(store.Rejected, match="其他管理员"):
        privacy.save(privacy.PrivacyPolicy(), "inoe:admin")
    privacy.save(privacy.PrivacyPolicy(revision=1), "inoe:admin")
    await privacy.check("model_context", [{"content": sample}])
    assert len(privacy.status()["hits"]) == 2


@pytest.mark.asyncio
async def test_model_wrapper_blocks_before_provider_with_message_objects_and_json():
    provider = AsyncMock(return_value=SimpleNamespace(usage=None))
    provider.model = "privacy-test-model"
    provider.parameters = None
    provider.credential = None
    provider.stream = False
    provider.context_size = 32768
    structured = provider.generate_structured_output
    model = RetryChatModel(provider)
    privacy.save(privacy.PrivacyPolicy(model_context="block", builtin=["手机号", "银行卡号"]), "test-admin")
    history = [Msg(name="user", role="user", content=[TextBlock(text="手机号 19900"), TextBlock(text="000000")])]
    with pytest.raises(privacy.PrivacyBlocked):
        await model(history)
    with pytest.raises(privacy.PrivacyBlocked):
        await model.generate_structured_output(messages=history, structured_model={})
    with pytest.raises(privacy.PrivacyBlocked):
        await model(messages=[{"tool_calls": [{"function": {"arguments": '{"银行卡号":"1234567890123456"}'}}]}])
    provider.assert_not_awaited()
    structured.assert_not_awaited()
    assert privacy.status()["hits"][0]["scene"] == "model_context"
    assert len(privacy.status()["hits"]) == 3
    await model(messages=[{"role": "user", "content": "你好"}])
    provider.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_boundary_blocks_before_chat_creation_and_task_dispatch(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request

    privacy.save(privacy.PrivacyPolicy(chat_input="block"), "test-admin")
    channel = SimpleNamespace(resolve_session_id=AsyncMock(), stream_one=AsyncMock())
    workspace = SimpleNamespace(channel_manager=SimpleNamespace(get_channel=AsyncMock(return_value=channel)))
    monkeypatch.setattr(console, "get_agent_for_request", AsyncMock(return_value=workspace))
    monkeypatch.setattr(console, "chat_scope", lambda: None)
    monkeypatch.setattr(console.trusted_chat_text, "enabled", lambda: False)
    request = Request({"type": "http", "path": "/api/console/chat", "headers": []})
    data = {"input": [{"role": "user", "content": [{"type": "text", "text": "19900000000"}]}]}
    for route in (console.post_console_chat, console.post_console_chat_task):
        with pytest.raises(HTTPException) as error:
            await route(data, request)
        assert error.value.status_code == 403 and "19900000000" not in error.value.detail
    channel.resolve_session_id.assert_not_called()
    channel.stream_one.assert_not_called()


@pytest.mark.asyncio
async def test_unreadable_saved_policy_does_not_allow_model_request():
    store.STORE_DIR.mkdir()
    (store.STORE_DIR / "privacy-policy.sqlite3").write_bytes(b"invalid SQLite database")
    with pytest.raises(privacy.PrivacyUnavailable):
        await privacy.check("model_context", [{"content": "text"}])
