from datetime import datetime, timezone

from qwenpaw.extensions.integrations.portal_real_alarms import query_portal_real_alarms


def test_query_portal_real_alarms_normalizes_live_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        lambda *, limit, begin_time, end_time: {
            "code": 200,
            "total": 1,
            "rows": [
                {
                    "alarmuniqueid": "COMMON__1776338881568_2044739586778116096",
                    "alarmtitle": "数据库锁异常",
                    "alarmseverity": "1",
                    "alarmstatus": "1",
                    "eventtime": "2026-04-15 19:20:00",
                    "devName": "MySQL",
                    "manageIp": "10.43.150.186",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._load_mock_alarm_rows",
        lambda: [],
    )

    payload = query_portal_real_alarms(
        limit=10,
        now=datetime(2026, 4, 17, 1, 0, 0, tzinfo=timezone.utc),
    )

    assert payload["source"] == "live"
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == "COMMON__1776338881568_2044739586778116096"
    assert payload["items"][0]["level"] == "critical"
    assert payload["items"][0]["employeeId"] == "fault"
    assert payload["items"][0]["dispatchContent"] == "mysql/死锁 + cmdb/新增/插入"


def test_query_portal_real_alarms_falls_back_to_mock_when_live_rows_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        lambda *, limit, begin_time, end_time: {"code": 200, "total": 0, "rows": []},
    )
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._load_mock_alarm_rows",
        lambda: [
            {
                "alarmuniqueid": "mock-deadlock-1",
                "alarmtitle": "数据库锁异常",
                "alarmseverity": "1",
                "alarmstatus": "1",
                "eventtime": "2026-04-15 19:20:00",
                "devName": "MySQL",
                "manageIp": "10.43.150.186",
            }
        ],
    )

    payload = query_portal_real_alarms(limit=10)

    assert payload["source"] == "mock"
    assert payload["total"] == 1
    assert payload["items"][0]["visibleContent"] == "数据库锁异常（MySQL 10.43.150.186）"


def test_query_portal_real_alarms_falls_back_to_mock_on_request_failure(monkeypatch) -> None:
    def _raise_request_error(*, limit, begin_time, end_time):
        raise RuntimeError("gateway unavailable")

    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        _raise_request_error,
    )
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._load_mock_alarm_rows",
        lambda: [
            {
                "alarmuniqueid": "mock-deadlock-2",
                "alarmtitle": "数据库锁异常",
                "alarmseverity": "1",
                "alarmstatus": "1",
                "eventtime": "2026-04-15 19:20:00",
                "devName": "MySQL",
                "manageIp": "10.43.150.186",
            }
        ],
    )

    payload = query_portal_real_alarms(limit=10)

    assert payload["source"] == "mock"
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == "mock-deadlock-2"


def test_query_portal_real_alarms_sends_last_7_days_active_alarm_request(monkeypatch) -> None:
    captured = {}

    def _fake_post(*, limit, begin_time, end_time):
        captured["limit"] = limit
        captured["begin_time"] = begin_time
        captured["end_time"] = end_time
        return {"code": 200, "total": 0, "rows": []}

    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        _fake_post,
    )
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._load_mock_alarm_rows",
        lambda: [],
    )

    query_portal_real_alarms(
        limit=5,
        now=datetime(2026, 4, 17, 1, 0, 0, tzinfo=timezone.utc),
    )

    assert captured["limit"] == 5
    assert captured["begin_time"] == "2026-04-10 01:00:00"
    assert captured["end_time"] == "2026-04-17 01:00:00"
