"""The Portal alarm export limit is applied before sending any file."""
import sqlite3
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.agents.tools.prepare_alarm_export import prepare_alarm_export
from qwenpaw.extensions.api import alarm_export
from qwenpaw.extensions.api.access_policy import requires_admin
from qwenpaw.extensions.api.access_session import AccessIdentity, CURRENT_IDENTITY
from qwenpaw.extensions.integrations import portal_real_alarms

BASE = "/api/portal"
REGISTRY = {"source": "registry"}
LIVE = {"source": "live", "begin_time": "2026-11-20 12:00:00",
        "end_time": "2026-11-21 12:00:00", "is_clear": "0", "severity": "1,2"}
ADMIN = {"x-test-actor": "admin"}


def records(count):
    return {str(i): {"alarmId": str(i), "title": f"告警 {i}",
                     "status": "new" if i < 10 else "resolved"}
            for i in range(count)}


@pytest.fixture
def api(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    from qwenpaw.extensions.api import controlled_documents, work_order_export
    from qwenpaw.security import secret_store
    from qwenpaw.governance import component_events

    monkeypatch.setattr(alarm_export.runtime_data_paths, "SETTINGS_DATA_DIR", tmp_path)
    monkeypatch.setattr(controlled_documents, "STORE_DIR", tmp_path / "private")
    monkeypatch.setattr(component_events, "WORKING_DIR", tmp_path / "audit")
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "admin")
    monkeypatch.setenv("QWENPAW_TRUSTED_CHAT_ISOLATION", "false")
    fernet = Fernet(Fernet.generate_key())
    monkeypatch.setattr(secret_store, "_get_fernet", lambda: fernet)
    data = records(100)
    monkeypatch.setattr(alarm_export, "load_alarm_records", lambda: data)
    app = FastAPI()
    app.include_router(alarm_export.router, prefix=BASE)
    app.include_router(work_order_export.router, prefix=BASE)

    @app.middleware("http")
    async def identity_for_test(request, call_next):
        actor = request.headers.get("x-test-actor", "alice")
        identity = None if actor == "anonymous" else AccessIdentity(
            {"userId": actor}, "" if actor == "local-only" else "fixture-token",
        )
        token = CURRENT_IDENTITY.set(identity)
        try:
            return await call_next(request)
        finally:
            CURRENT_IDENTITY.reset(token)

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, data, tmp_path


async def preview(client, selection, **options):
    return await client.post(BASE + "/alarm-export/preview", json=selection, **options)


async def download(client, selection, ticket, **options):
    return await client.post(BASE + "/alarm-export/download", json={"selection": selection, "ticket": ticket}, **options)


@pytest.mark.parametrize("count", [0, 9, 10, 11, 100])
async def test_boundary_blocks_without_truncating_or_returning_rows(api, count):
    client, data, path = api
    data.clear()
    data.update(records(count))
    async with client:
        result = await preview(client, REGISTRY)
        assert result.status_code == 200
        status = result.json()
        assert status["count"] == count and status["max_rows"] == 10
        assert "items" not in status
        if 0 < count <= 10:
            output = await download(client, REGISTRY, status["ticket"])
            assert output.status_code == 200
            assert output.json()["total"] == len(output.json()["items"]) == count
            assert "attachment" in output.headers["Content-Disposition"]
        else:
            assert "ticket" not in status
            if count:
                assert f"导出 {count} 条，单次最多 10 条" in status["message"]
            denied = await download(client, REGISTRY, "a" * 43)
            assert denied.status_code == 409 and "Content-Disposition" not in denied.headers
        old = await client.get(BASE + "/alarm-registry/export")
        assert old.status_code == (422 if count > 10 else 409)
        assert "items" not in old.json()
    if count:
        with sqlite3.connect(path / "alarm_export.db") as db:
            assert db.execute("SELECT decision FROM events LIMIT 1").fetchone() == (
                "released" if count <= 10 else "blocked_limit",
            )


async def test_admin_setting_and_confirmation_are_enforced_server_side(api):
    client, data, _ = api
    assert not requires_admin("POST", BASE + "/alarm-export/preview")
    assert requires_admin("PUT", BASE + "/alarm-export-settings")
    async with client:
        settings = BASE + "/alarm-export-settings"
        assert (await client.get(settings)).status_code == 403
        assert (await client.put(settings, json={"max_rows": 4})).status_code == 403
        assert (await client.put(settings, json={"max_rows": 4}, headers={**ADMIN, "Origin": "http://other"})).status_code == 403
        assert (await client.put(settings, json={"max_rows": "4"}, headers=ADMIN)).status_code == 422
        selection = {**REGISTRY, "status": "new"}
        ticket = (await preview(client, selection)).json()["ticket"]
        assert (await download(client, selection, ticket, headers={"x-test-actor": "bob"})).status_code == 409
        assert (await preview(client, selection, headers={"x-test-actor": "anonymous"})).status_code == 401
        assert (await client.put(settings, json={"max_rows": 9}, headers=ADMIN)).json() == {"max_rows": 9}
        blocked = await download(client, selection, ticket)
        assert blocked.status_code == 422 and "单次最多 9 条" in blocked.json()["detail"]
        filtered = {**selection, "search": "告警 3"}
        ticket = (await preview(client, filtered)).json()["ticket"]
        data["3"]["eventTime"] = "just changed"
        assert (await download(client, filtered, ticket)).status_code == 409
        ticket = (await preview(client, filtered)).json()["ticket"]
        assert (await download(client, REGISTRY, ticket)).status_code == 422
        ticket = (await preview(client, filtered)).json()["ticket"]
        assert (await download(client, filtered, ticket)).status_code == 200
        assert (await download(client, filtered, ticket)).status_code == 409


async def test_chat_export_uses_real_total_and_callers_scope(api, monkeypatch):
    client, _, _ = api
    calls = []
    gateway = {"total": 100, "rows": [{"alarmuniqueid": "A"}] * 10}

    def list_alarms(**kwargs):
        calls.append(kwargs)
        assert portal_real_alarms._build_real_alarm_headers()["Authorization"] == "Bearer fixture-token"
        return gateway

    monkeypatch.setattr(portal_real_alarms, "_post_real_alarm_list", list_alarms)
    async with client:
        denied = await preview(client, LIVE, headers={"x-test-actor": "local-only"})
        assert denied.status_code == 403 and not calls
        result = (await preview(client, LIVE)).json()
        assert result["count"] == 100 and "ticket" not in result
        assert calls[0]["limit"] == 10 and calls[0]["begin_time"] == LIVE["begin_time"]
        assert calls[0]["filters"]["alarmSeverity"] == "1,2"
        gateway.update(total=9, rows=[{"alarmuniqueid": "A"}])
        assert (await preview(client, LIVE)).status_code == 502
        gateway.update(total=None)
        assert (await preview(client, LIVE)).status_code == 502
        gateway.update(total="1")
        ticket = (await preview(client, LIVE)).json()["ticket"]
        output = await download(client, LIVE, ticket)
        assert output.json()["items"][0]["alarmId"] == "A"


async def test_tool_checks_real_scope_and_enforces_limit_before_link(api, monkeypatch):
    client, _, path = api
    calls = []
    count = 1

    def read_rows(limit, start, end, filters):
        calls.append((limit, start, end, filters))
        return count, [{"alarmId": "demo"}] if count <= limit else []

    monkeypatch.setattr(alarm_export, "read_alarm_export_rows", read_rows)
    token = CURRENT_IDENTITY.set(AccessIdentity({"userId": "alice"}, "fixture-token"))
    try:
        content = (await prepare_alarm_export(
            LIVE["begin_time"], LIVE["end_time"], "0", "1,2", "设备（甲）/1",
        )).content[0].text
        count = 41
        denied = (await prepare_alarm_export(
            LIVE["begin_time"], LIVE["end_time"], "0", "1,2", "设备（甲）/1",
        )).content[0].text
    finally:
        CURRENT_IDENTITY.reset(token)
        await client.aclose()
    assert calls == [(10, LIVE["begin_time"], LIVE["end_time"],
                      {"isClear": "0", "alarmSeverity": "1,2", "queryKey": "设备（甲）/1"})] * 2
    assert "导出 41 条，单次最多 10 条" in denied and "](" not in denied
    with sqlite3.connect(path / "alarm_export.db") as db:
        assert db.execute("SELECT decision, records FROM events").fetchall() == [("agent_blocked_limit", 41)]
        assert db.execute("SELECT count(*) FROM tickets").fetchone()[0] == 0
    path = content.split("](", 1)[1].removesuffix(")")
    query = parse_qs(urlsplit(path).query)
    assert urlsplit(path).path == BASE + "/alarm-export/preview"
    assert query["keyword"] == ["设备（甲）/1"]
    assert query["begin_time"] == [LIVE["begin_time"]]


def test_export_uses_same_exact_ip_filter_as_alarm_query():
    params = portal_real_alarms.build_real_alarm_list_query_params(
        page_num=1, page_size=10, begin_time=LIVE["begin_time"],
        end_time=LIVE["end_time"],
        filters={"neIp": "10.0.0.1", "isClear": "1", "pageSize": "100"},
    )
    assert params["neIp"] == "10.0.0.1" and params["isLike"] == "0"
    assert params["isClear"] == "1" and params["pageSize"] == 10


async def test_unverified_scopes_are_not_exported(api):
    client, _, _ = api
    async with client:
        for invalid in (
            {"is_clear": "all"},
            {"begin_time": "2026-11-22 12:00:00"},
            {"keyword": "Router", "manage_ip": "10.0.0.1"},
        ):
            assert (await preview(client, {**LIVE, **invalid})).status_code == 422


@pytest.mark.parametrize("allowed_limit", [41, 100])
async def test_work_order_export_respects_shared_policy_and_releases_only_after_confirmation(api, monkeypatch, allowed_limit):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from agentscope.message import ToolResultState
    from qwenpaw.drivers.adapters.agentscope_tool import build_driver_agent_tools
    from qwenpaw.drivers.capabilities import (
        CapabilityExposure, DriverCapability, DriverInvocationResult,
    )

    from qwenpaw.extensions.security import call_admission

    client, _, path = api
    monkeypatch.setattr(call_admission, "WORKING_DIR", path)
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    capability = DriverCapability(
        "driver://mcp/order/tools/listWorkOrders#invoke", "order", "mcp",
        "tool", "invoke", "listWorkOrders",
        input_schema={"properties": {"startTime": {"type": "string"}}},
        exposure=CapabilityExposure(as_tool=True, tool_name="order__listWorkOrders"),
    )
    upstream = SimpleNamespace(
        isError=False,
        structuredContent={"code": 200, "data": {
            "total_count": 41, "data": [{"id": i + 1, "title": f"not exposed {i + 1}"} for i in range(10)],
        }},
    )
    manager = SimpleNamespace(
        list_drivers=AsyncMock(return_value=[SimpleNamespace(
            name="order", enabled=True, status="active", protocol="mcp",
        )]),
        list_driver_capabilities=AsyncMock(return_value=[capability]),
        invoke_capability=AsyncMock(return_value=DriverInvocationResult(ok=True, value=upstream)),
    )
    tools, _ = await build_driver_agent_tools(manager, {"user_id": "alice"})
    assert {tool.name for tool in tools} == {"order__listWorkOrders", "check_work_order_export"}
    tool = next(tool for tool in tools if tool.name == "check_work_order_export")
    token = CURRENT_IDENTITY.set(AccessIdentity({"userId": "alice"}, "fixture-token"))
    try:
        async with client:
            filters = {"classify": 5, "startTime": "2026-11-20 00:00:00"}
            blocked = await tool(**filters)
            assert blocked.state == ToolResultState.DENIED
            assert "已触发导出管控上限" in blocked.content[0].text
            assert "41 条已办工单，单次最多导出 10 条" in blocked.content[0].text
            assert "not exposed" not in blocked.content[0].text
            assert "](" not in blocked.content[0].text
            manager.invoke_capability.assert_awaited_once()
            invocation = manager.invoke_capability.call_args.args[0]
            assert invocation.capability_id == capability.capability_id
            assert invocation.request_context == {"user_id": "alice"}
            assert invocation.payload == {**filters, "page": 1, "per_page": 10}

            settings = BASE + "/alarm-export-settings"
            assert (await client.put(settings, json={"max_rows": allowed_limit}, headers=ADMIN)).status_code == 200
            rows = [{"id": i + 1, "title": f"not exposed {i + 1}"} for i in range(41)]
            upstream.structuredContent["data"]["data"] = rows
            within = await tool(**filters)
            assert within.state == ToolResultState.SUCCESS
            assert f"41 条已办工单，单次最多导出 {allowed_limit} 条" in within.content[0].text
            assert "not exposed" not in within.content[0].text
            intent = within.content[0].text.split("?intent=", 1)[1].split(")", 1)[0]
            intent_body = {"intent": intent}
            root = BASE + "/work-order-export"
            assert not requires_admin("POST", root + "/download")
            with sqlite3.connect(path / "alarm_export.db") as db:
                saved = db.execute("SELECT hash, snapshot FROM work_order_exports").fetchone()
                assert saved[0] != intent and saved[1].startswith("ENC:") and "not exposed" not in saved[1]
            assert (await client.get(root + "/preview", params=intent_body)).status_code == 405
            assert (await client.post(root + "/preview", json=intent_body, headers={"x-test-actor": "bob"})).status_code == 409
            assert (await client.post(root + "/preview", json=intent_body, headers={"x-test-actor": "anonymous"})).status_code == 401
            assert (await client.post(root + "/preview", json={**intent_body, "classify": 1})).status_code == 422
            assert (await client.post(root + "/download", json={**intent_body, "ticket": intent})).status_code == 409
            response = await client.post(root + "/preview", json=intent_body)
            assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
            preview_data = response.json()
            assert preview_data["count"] == 41 and preview_data["max_rows"] == allowed_limit and preview_data["scope"] == filters
            assert "not exposed" not in response.text
            body = {**intent_body, "ticket": preview_data["ticket"]}
            assert (await client.post(root + "/download", json=body, headers={"x-test-actor": "bob"})).status_code == 409
            assert (await client.post(root + "/download", json=body, headers={"Origin": "https://foreign.invalid"})).status_code == 403
            downloaded = await client.post(root + "/download", json=body)
            assert downloaded.status_code == 200, downloaded.text
            assert "work-orders.json" in downloaded.headers["Content-Disposition"]
            assert downloaded.json() == {"total": 41, "items": rows}
            assert (await client.post(root + "/download", json=body)).status_code == 409
            assert manager.invoke_capability.await_count == 2  # confirmation releases exactly the prepared rows

            upstream.structuredContent["data"].pop("total_count")
            unknown = await tool(**filters)
            assert "无法核实" in unknown.content[0].text and "已触发" not in unknown.content[0].text
            upstream.structuredContent["data"] = {"total_count": 0, "data": []}
            empty = await tool(classify=1)
            assert "0 条待办工单" in empty.content[0].text and "没有可导出" in empty.content[0].text
            count_calls = manager.invoke_capability.await_count
            for invalid in ({"count": 100}, {"title": "限定标题"}, {"startTime": "随便"}, {"per_page": 999}):
                message = await tool(classify=5, **invalid)
                assert "确认筛选条件" in message.content[0].text
            unsupported = await tool(classify=5, endTime="2026-11-20 23:59:59")
            assert "不支持指定的时间筛选" in unsupported.content[0].text
            assert manager.invoke_capability.await_count == count_calls

            manager.invoke_capability.return_value = DriverInvocationResult(
                ok=False, error_type="permission_denied", message="internal detail",
            )
            denied = await tool(**filters)
            assert denied.state == ToolResultState.DENIED
            assert "未获授权" in denied.content[0].text and "internal detail" not in denied.content[0].text
    finally:
        CURRENT_IDENTITY.reset(token)
    with sqlite3.connect(path / "alarm_export.db") as db:
        assert db.execute("SELECT actor, decision, records, max_rows FROM events WHERE source='work_order'").fetchall() == [
            ("alice", "agent_blocked_limit", 41, 10), ("alice", "released", 41, allowed_limit),
        ]
        assert db.execute("SELECT count(*) FROM tickets").fetchone()[0] == 0


@pytest.mark.parametrize("value, expected", [
    ({"result": {"data": {"total_count": "41"}}}, 41),
    ({"total": 41, "totalCount": 4}, None),
    ({"total": True}, None),
    ({"total": 1.0}, None),
    ({"code": 403, "data": {"total_count": 41}}, None),
    ({"total": 0, "rows": [{}]}, None),
    ({"rows": [{"title": "total: 41"}]}, None),
])
def test_work_order_total_requires_authoritative_structured_value(value, expected):
    from qwenpaw.drivers.adapters.work_order_export import upstream_work_order_total

    assert upstream_work_order_total(value) == expected



async def test_sensitive_alarm_export_rechecks_policy_at_download(api):
    from qwenpaw.extensions.api import text_privacy

    client, data, path = api
    data.clear()
    data.update(records(1))
    data["0"]["title"] = "内部编号：DEMO-SENSITIVE"
    async with client:
        ticket = (await preview(client, REGISTRY)).json()["ticket"]
        text_privacy.save(text_privacy.PrivacyPolicy(builtin=[], custom_fields=["内部编号"], exports="block"), "admin")
        denied = await download(client, REGISTRY, ticket)
        assert denied.status_code == 422 and "阻止导出" in denied.json()["detail"]
        assert "DEMO-SENSITIVE" not in denied.text and "Content-Disposition" not in denied.headers
        assert (await preview(client, REGISTRY)).status_code == 422
    with sqlite3.connect(path / "alarm_export.db") as db:
        assert db.execute("SELECT decision FROM events").fetchall() == [("blocked_privacy",)]


@pytest.mark.parametrize("change, status, decision", [
    ("limit", 422, "blocked_limit"),
    ("privacy", 422, "blocked_privacy"),
    ("expired", 409, None),
    ("revoked", 403, "blocked_access"),
])
async def test_work_order_rechecks_boundaries_after_browser_confirmation(api, monkeypatch, change, status, decision):
    from qwenpaw.extensions.api import text_privacy, work_order_export

    client, _, path = api
    selection = {"classify": 5}
    rows = [{"id": i + 1, "title": "客户编号：DEMO-WO"} for i in range(4)]
    token = CURRENT_IDENTITY.set(AccessIdentity({"userId": "alice"}, "fixture-token"))
    try:
        intent, _ = work_order_export.prepare(selection, rows, "")
    finally:
        CURRENT_IDENTITY.reset(token)
    async with client:
        root = BASE + "/work-order-export"
        response = await client.post(root + "/preview", json={"intent": intent})
        body = {"intent": intent, "ticket": response.json()["ticket"]}
        if change == "limit":
            await client.put(BASE + "/alarm-export-settings", json={"max_rows": 3}, headers=ADMIN)
        elif change == "privacy":
            text_privacy.save(text_privacy.PrivacyPolicy(builtin=[], custom_fields=["客户编号"], exports="block"), "admin")
        elif change == "expired":
            with sqlite3.connect(path / "alarm_export.db") as db:
                db.execute("UPDATE work_order_exports SET expires=0")
        else:
            def denied(_):
                raise PermissionError
            monkeypatch.setattr(work_order_export, "require_not_blocked", denied)
        blocked = await client.post(root + "/download", json=body)
        assert blocked.status_code == status, blocked.text
        assert "DEMO-WO" not in blocked.text and "Content-Disposition" not in blocked.headers
        if change == "limit":
            assert "4 条已办工单，单次最多导出 3 条" in blocked.json()["detail"]
        assert (await client.post(root + "/download", json=body)).status_code == 409
    with sqlite3.connect(path / "alarm_export.db") as db:
        assert db.execute("SELECT decision FROM events WHERE source='work_order'").fetchall() == ([(decision,)] if decision else [])


@pytest.mark.parametrize("duplicate", [False, True])
async def test_work_order_bounded_pagination_keeps_scope_and_rejects_duplicate_rows(api, duplicate):
    from unittest.mock import AsyncMock
    from agentscope.message import ToolResultState
    from qwenpaw.drivers.adapters.work_order_export import preflight
    from qwenpaw.drivers.capabilities import DriverInvocationResult

    _, _, path = api
    pages = [
        {"total_count": 3, "page": 1, "per_page": 2, "data": [{"id": 1}, {"id": 2}]},
        {"total_count": 3, "page": 2, "per_page": 2, "data": [{"id": 1 if duplicate else 3}]},
    ]
    dispatch = AsyncMock(side_effect=[DriverInvocationResult(ok=True, value={"data": page}) for page in pages])
    filters = {"classify": 5, "endTime": "2026-11-20 23:59:59"}
    identity = CURRENT_IDENTITY.set(AccessIdentity({"userId": "alice"}, "fixture-token"))
    try:
        state, result = await preflight(dispatch, "fixture", {}, filters, page_size_cap=2)
        assert [call.args[0].payload for call in dispatch.await_args_list] == [
            {**filters, "page": 1, "per_page": 2}, {**filters, "page": 2, "per_page": 2},
        ]
    finally:
        CURRENT_IDENTITY.reset(identity)
    assert state == (ToolResultState.ERROR if duplicate else ToolResultState.SUCCESS), result.text
    assert ("?intent=" in result.text) == (not duplicate)
    with sqlite3.connect(path / "alarm_export.db") as db:
        assert db.execute("SELECT count(*) FROM work_order_exports").fetchone()[0] == int(not duplicate)


def test_work_order_intent_creation_requires_the_original_scoped_actor(api, monkeypatch):
    from fastapi import HTTPException
    from qwenpaw.extensions.api import work_order_export
    from qwenpaw.extensions.api.chat_isolation import chat_scope
    from qwenpaw.extensions.security import portal_capabilities as permissions

    monkeypatch.setenv("QWENPAW_TRUSTED_CHAT_ISOLATION", "true")
    alice = CURRENT_IDENTITY.set(AccessIdentity({"userId": "alice"}, "fixture-token"))
    try:
        chat = chat_scope()
        scoped = permissions.invocation_for(chat.owner, "order", chat.session_id("fixture"), "console")
        context = {permissions.CONTEXT_KEY: scoped}
        assert work_order_export.verify_actor_scope(context) == "order"
        with pytest.raises(HTTPException) as absent:
            work_order_export.verify_actor_scope({})
        assert absent.value.status_code == 403
        bob = CURRENT_IDENTITY.set(AccessIdentity({"userId": "bob"}, "fixture-token"))
        try:
            with pytest.raises(HTTPException) as foreign:
                work_order_export.verify_actor_scope(context)
            assert foreign.value.status_code == 403
        finally:
            CURRENT_IDENTITY.reset(bob)
    finally:
        CURRENT_IDENTITY.reset(alice)
