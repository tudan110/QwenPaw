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
    monkeypatch.setattr(alarm_export.runtime_data_paths, "SETTINGS_DATA_DIR", tmp_path)
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "admin")
    data = records(100)
    monkeypatch.setattr(alarm_export, "load_alarm_records", lambda: data)
    app = FastAPI()
    app.include_router(alarm_export.router, prefix=BASE)

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
