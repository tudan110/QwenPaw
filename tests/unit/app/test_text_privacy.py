"""Text privacy policies are persisted and used before dispatch, not UI flags."""
from pathlib import Path
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



def _set_modes(**modes):
    current = privacy.load_policy()
    privacy.save(privacy.PrivacyPolicy.model_validate({
        **current.model_dump(), "builtin": [], "custom_fields": ["客户编号"], **modes,
    }), "test-admin")


def test_legacy_policy_defaults_only_new_scenes_to_off():
    from typing import get_args

    previous = '{"revision":5,"builtin":[],"custom_fields":["客户编号"],"chat_input":"observe","model_context":"block"}'
    with privacy._connection(write=True) as db, db:
        db.execute("INSERT INTO privacy_policy VALUES (1, ?)", (previous,))
    status = privacy.status()
    saved = status["policy"]
    assert saved["revision"] == 5 and saved["chat_input"] == "observe" and saved["model_context"] == "block"
    scenes = {scene["id"] for scene in status["scenes"]}
    assert scenes == set(get_args(privacy.Scene)) == set(saved) - {"revision", "builtin", "custom_fields"}
    assert all(saved[scene] == "off" for scene in scenes - {"chat_input", "model_context"})
    for scene in scenes:
        with pytest.raises(ValueError, match="至少选择一条"):
            privacy.PrivacyPolicy(builtin=[], **{scene: "block"})


def test_log_handlers_check_the_formatted_message_and_exception_once(tmp_path):
    import io
    import logging
    from qwenpaw.utils.logging import _filter_sensitive_logs

    logger = logging.Logger("privacy-test")
    console_stream = io.StringIO()
    logfile = tmp_path / "managed.log"
    for handler in (logging.StreamHandler(console_stream), logging.FileHandler(logfile, encoding="utf-8")):
        _filter_sensitive_logs(handler)
        logger.addHandler(handler)
    try:
        _set_modes(logs="observe")
        logger.warning("客户编号：%s", "DEMO-OBSERVED")
        _set_modes(logs="block")
        logger.warning("客户编号：%s", "DEMO-HIDDEN")
        try:
            raise RuntimeError("客户编号：DEMO-EXCEPTION")
        except RuntimeError:
            logger.exception("Exception example")
        logger.warning("CLEAN-EVENT")
    finally:
        for handler in logger.handlers:
            handler.close()
    for output in (console_stream.getvalue(), logfile.read_text(encoding="utf-8")):
        assert "DEMO-OBSERVED" in output and "CLEAN-EVENT" in output
        assert "DEMO-HIDDEN" not in output and "DEMO-EXCEPTION" not in output
    assert [hit["decision"] for hit in privacy.status()["hits"]] == ["blocked", "blocked", "observed"]


@pytest.mark.asyncio
async def test_cache_blocks_tool_snapshots_and_compressed_context(tmp_path):
    from qwenpaw.agents.offloader import QwenPawOffloader

    offloader = QwenPawOffloader(str(tmp_path / "dialog"), str(tmp_path / "tools"))
    _set_modes(cache="block")
    raw = "客户编号：DEMO-CACHE"
    assert not await offloader.offload_tool_result("fixture", SimpleNamespace(output=[TextBlock(text=raw)]))
    assert not await offloader.offload_context("fixture", [Msg(name="user", role="user", content=[TextBlock(text=raw)])])
    assert not (tmp_path / "tools").exists() and not (tmp_path / "dialog").exists()
    clean = await offloader.offload_tool_result("fixture", SimpleNamespace(output=[TextBlock(text="clean result")]))
    assert Path(clean).read_text(encoding="utf-8") == "clean result"
    assert await offloader.offload_context("fixture", [Msg(name="user", role="user", content=[TextBlock(text="clean context")])])
    assert len(privacy.status()["hits"]) == 2


@pytest.mark.asyncio
async def test_debug_checks_session_and_task_trace_writes_and_old_log_reads(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from qwenpaw.app import inbox_trace_store
    from qwenpaw.extensions.traceability import trace_store

    traces = tmp_path / "traces"
    inbox = tmp_path / "inbox"
    log = tmp_path / "old.log"
    monkeypatch.setattr(trace_store, "_TRACE_DIR", traces)
    monkeypatch.setattr(trace_store, "_INDEX_PATH", traces / "_index.json")
    monkeypatch.setattr(inbox_trace_store, "_TRACE_DIR", inbox)
    monkeypatch.setattr(console, "LOG_FILE_PATH", log)
    raw = "客户编号：DEMO-TRACE"
    log.write_text(raw, encoding="utf-8")
    _set_modes(debug="block")
    await trace_store.record_event("demo", "note", {"text": raw})
    await inbox_trace_store.create_trace("demo", meta={"description": raw})
    await inbox_trace_store.append_trace_events("demo", [{"event": {"text": raw}}])
    assert not inbox.exists() and not traces.exists()
    await inbox_trace_store.finalize_trace("demo", status="failed", error=raw)
    assert "error" not in await inbox_trace_store.get_trace("demo")
    with pytest.raises(HTTPException) as err:
        await console.get_backend_debug_logs(lines=20)
    assert err.value.status_code == 422 and "DEMO-TRACE" not in err.value.detail
    assert log.read_text(encoding="utf-8") == raw
    await trace_store.record_event("demo", "note", {"text": "clean trace"})
    assert (traces / "_index.json").is_file()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["off", "observe", "block"])
async def test_query_policy_handles_streams_before_output_or_context(mode):
    from agentscope.message import ToolResultState
    from agentscope.tool import ToolChunk, ToolResponse
    from qwenpaw.agents.result_privacy import ToolResultPrivacyMiddleware

    _set_modes(query_results=mode)
    middleware = ToolResultPrivacyMiddleware()
    call = {"tool_call": SimpleNamespace(id="call")}

    async def events(*parts):
        result = ToolResponse(id="call")
        for part in parts:
            chunk = ToolChunk(content=[TextBlock(id="text", text=part)], is_last=False)
            result.append_chunk(chunk)
            yield chunk
        yield result

    result = [e async for e in middleware.on_acting(None, call, lambda **_: events("客户编", "号：DEMO-RESULT"))]
    if mode == "block":
        assert len(result) == 2 and all(e.state == ToolResultState.DENIED for e in result)
        assert "DEMO-RESULT" not in str(result) and "阻止返回" in result[-1].content[0].text
        clean = [e async for e in middleware.on_acting(None, call, lambda **_: events("正常", "结果"))]
        assert len(clean) == 2 and clean[0].content[0].text == "正常结果"
        assert clean[-1].state == ToolResultState.SUCCESS
    else:
        assert len(result) == 3 and result[-1].content[0].text == "客户编号：DEMO-RESULT"
    assert len(privacy.status()["hits"]) == (mode != "off")


def test_knowledge_upload_rejects_sensitive_and_unsupported_files_before_storage(tmp_path, monkeypatch):
    from qwenpaw.extensions.integrations import knowledge_base

    storage = tmp_path / "kb"
    monkeypatch.setattr(knowledge_base, "data_dir", lambda: storage)
    _set_modes(knowledge="block")
    # Rejected files must not reach the upload directory or ingestion worker.
    with pytest.raises(privacy.PrivacyBlocked, match="阻止入库"):
        knowledge_base.create_ingest_job("sample.txt", "客户编号：DEMO-UPLOAD".encode())
    with pytest.raises(privacy.PrivacyBlocked, match="无法检查正文"):
        knowledge_base.create_ingest_job("sample.pdf", b"%PDF-fake")
    assert not storage.exists()
    knowledge_base.check_upload_privacy("sample.txt", "正常文档".encode())
    _set_modes(knowledge="observe")
    knowledge_base.check_upload_privacy("sample.pdf", b"%PDF-fake")
    knowledge_base.check_upload_privacy("sample.txt", "客户编号：DEMO-UPLOAD".encode())
    assert [hit["decision"] for hit in privacy.status()["hits"]] == ["observed", "blocked"]



def test_business_lists_apply_query_policy_before_returning_details(monkeypatch):
    from fastapi.testclient import TestClient
    from qwenpaw.extensions.api import portal_backend

    raw = {"title": "客户编号：DEMO-LIST"}
    result = {"total": 1, "items": [raw]}
    monkeypatch.setattr(portal_backend, "query_alarm_workorders", lambda limit: result)
    monkeypatch.setattr(portal_backend, "_get_visible_portal_real_alarms", AsyncMock(return_value=result))
    monkeypatch.setattr(portal_backend, "load_alarm_records", lambda: {"fixture": raw})
    monkeypatch.setattr(portal_backend, "filter_alarm_records", lambda records, *_: list(records))
    with TestClient(portal_backend.app) as client:
        for mode in ("observe", "block"):
            _set_modes(query_results=mode)
            for path in ("alarm-workorders", "real-alarms", "alarm-registry/records"):
                response = client.get(f"/api/portal/{path}")
                assert response.status_code == (422 if mode == "block" else 200), response.text
                assert ("DEMO-LIST" in response.text) == (mode == "observe")
    assert [hit["scene"] for hit in privacy.status()["hits"]] == ["query_results"] * 6
