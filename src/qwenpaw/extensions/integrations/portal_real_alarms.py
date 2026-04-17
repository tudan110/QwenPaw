from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

GATEWAY_REAL_ALARM_URL = "http://gateway:30080/resource/realalarm/list"
REAL_ALARM_TIMEOUT_SECONDS = 8.0
DEFAULT_REAL_ALARM_LIMIT = 10
MAX_REAL_ALARM_LIMIT = 50
MOCK_DATA_PATH = (
    Path(__file__).resolve().parents[4]
    / "deploy-all"
    / "qwenpaw"
    / "working"
    / "workspaces"
    / "fault"
    / "skills"
    / "real-alarm"
    / "mock_data.json"
)

SEVERITY_TO_LEVEL = {
    "1": "critical",
    "2": "urgent",
    "3": "warning",
}


def _format_dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _load_mock_alarm_rows() -> list[dict[str, Any]]:
    payload = json.loads(MOCK_DATA_PATH.read_text(encoding="utf-8"))
    return list(payload.get("rows") or [])


def _post_real_alarm_list(*, limit: int, begin_time: str, end_time: str) -> dict[str, Any]:
    body = {
        "pageNum": 1,
        "pageSize": limit,
        "alarmseverity": "",
        "alarmstatus": "1",
        "params": {
            "beginEventtime": begin_time,
            "endEventtime": end_time,
        },
    }
    with httpx.Client(timeout=REAL_ALARM_TIMEOUT_SECONDS) as client:
        response = client.post(GATEWAY_REAL_ALARM_URL, json=body)
        response.raise_for_status()
        return response.json()


def _normalize_alarm_row(row: dict[str, Any]) -> dict[str, Any]:
    severity = str(row.get("alarmseverity") or "").strip() or "4"
    device_name = str(row.get("devName") or "").strip() or "--"
    manage_ip = str(row.get("manageIp") or "").strip() or "--"
    title = str(row.get("alarmtitle") or "").strip() or "未命名告警"
    event_time = str(row.get("eventtime") or "")
    return {
        "id": str(row.get("alarmuniqueid") or title),
        "title": title,
        "level": SEVERITY_TO_LEVEL.get(severity, "info"),
        "status": "active",
        "eventTime": event_time,
        "timeLabel": event_time,
        "deviceName": device_name,
        "manageIp": manage_ip,
        "employeeId": "fault",
        "dispatchContent": "mysql/死锁 + cmdb/新增/插入",
        "visibleContent": f"{title}（{device_name} {manage_ip}）",
    }


def query_portal_real_alarms(limit: int, now: datetime | None = None) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or DEFAULT_REAL_ALARM_LIMIT), MAX_REAL_ALARM_LIMIT))
    current_time = now or datetime.now(timezone.utc)
    begin_time = _format_dt(current_time - timedelta(days=7))
    end_time = _format_dt(current_time)

    source = "live"
    try:
        result = _post_real_alarm_list(limit=safe_limit, begin_time=begin_time, end_time=end_time)
        rows = list(result.get("rows") or [])
    except Exception:
        source = "mock"
        rows = _load_mock_alarm_rows()
    else:
        if not rows:
            source = "mock"
            rows = _load_mock_alarm_rows()

    items = [_normalize_alarm_row(row) for row in rows[:safe_limit]]
    return {
        "total": len(items),
        "items": items,
        "source": source,
    }
