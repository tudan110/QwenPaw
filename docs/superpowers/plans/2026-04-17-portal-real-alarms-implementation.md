# Portal Real Alarms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated portal real-alarm backend/API/frontend flow that polls active alarms for the top-right bell, falls back to backend mock data during development, and dispatches a clicked alarm into the fault employee diagnosis chat without touching the existing `alarm-workorders` demo route.

**Architecture:** Keep the new behavior isolated by introducing a separate backend helper and `/api/portal/real-alarms` route that talks to `http://gateway:30080/resource/realalarm/list`, normalizes the payload into a portal-specific alert contract, and falls back to mock data when live data fails or is empty. On the frontend, add a dedicated real-alarm API client and a small alarm-mapping helper, then let `DigitalEmployeePage.tsx` poll the new route and feed its existing bell popup plus `pendingPortalDispatch` flow.

**Tech Stack:** FastAPI, pytest, httpx, React 18, TypeScript, Vite, pnpm

---

## File Structure

### Backend / integration

- Create: `src/qwenpaw/extensions/integrations/portal_real_alarms.py`
  - Own the gateway request, last-7-days request body, severity mapping, mock fallback, and final portal alert payload contract.
- Modify: `src/qwenpaw/extensions/api/portal_backend.py`
  - Register `GET /api/portal/real-alarms` and keep `/api/portal/alarm-workorders` untouched.
- Modify: `deploy-all/qwenpaw/working/workspaces/fault/skills/real-alarm/mock_data.json`
  - Add one MySQL deadlock-style active alarm row used by the new backend fallback.

### Frontend

- Create: `portal/src/api/portalRealAlarms.ts`
  - Typed client for `/portal-api/real-alarms`.
- Create: `portal/src/pages/digital-employee/realAlarms.ts`
  - Normalize backend real-alarm items into the existing `PortalOpsAlert` shape and define the poll interval.
- Modify: `portal/src/pages/DigitalEmployeePage.tsx`
  - Poll the new route, preserve the last successful result on poll failure, and reuse the existing click-to-dispatch behavior.

### Tests

- Create: `tests/unit/extensions/integrations/test_portal_real_alarms.py`
  - Cover normalization, request body shape, live-empty fallback, and live-error fallback.
- Modify: `tests/unit/extensions/api/test_portal_backend.py`
  - Cover the new route contract and confirm the helper output is passed through unchanged.

### Validation note

`portal` does not currently expose a dedicated frontend unit-test script in `package.json`, so frontend red/green validation uses `pnpm --dir portal run build`. Backend validation uses pytest.

---

### Task 1: Build the dedicated backend real-alarm helper and mock fallback

**Files:**
- Create: `src/qwenpaw/extensions/integrations/portal_real_alarms.py`
- Create: `tests/unit/extensions/integrations/test_portal_real_alarms.py`
- Modify: `deploy-all/qwenpaw/working/workspaces/fault/skills/real-alarm/mock_data.json`

- [ ] **Step 1: Write the failing helper tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/extensions/integrations/test_portal_real_alarms.py -q`

Expected: FAIL with `ModuleNotFoundError` for `qwenpaw.extensions.integrations.portal_real_alarms`

- [ ] **Step 3: Write the minimal helper and add the deadlock mock row**

```python
# src/qwenpaw/extensions/integrations/portal_real_alarms.py
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
    return {
        "id": str(row.get("alarmuniqueid") or title),
        "title": title,
        "level": SEVERITY_TO_LEVEL.get(severity, "info"),
        "status": "active",
        "eventTime": str(row.get("eventtime") or ""),
        "timeLabel": str(row.get("eventtime") or ""),
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
```

```json
// deploy-all/qwenpaw/working/workspaces/fault/skills/real-alarm/mock_data.json
{
  "rows": [
    {
      "alarmuniqueid": "COMMON__1776338881568_2044739586778116096",
      "alarmclass": "",
      "alarmtitle": "数据库锁异常",
      "devName": "MySQL",
      "manageIp": "10.43.150.186",
      "eventtime": "2026-04-15 19:20:00",
      "eventlasttime": "2026-04-17 03:34:24",
      "daltime": "2026-04-16 19:28:00",
      "alarmactcount": 196,
      "alarmstatus": "1",
      "alarmseverity": "1",
      "alarmSubType": "mySQL",
      "neAlias": "数据库",
      "alarmregion": "",
      "locatenename": ""
    }
  ]
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/extensions/integrations/test_portal_real_alarms.py -q`

Expected: PASS with `3 passed`

- [ ] **Step 5: Commit**

```bash
git add \
  src/qwenpaw/extensions/integrations/portal_real_alarms.py \
  tests/unit/extensions/integrations/test_portal_real_alarms.py \
  deploy-all/qwenpaw/working/workspaces/fault/skills/real-alarm/mock_data.json
git commit -m "feat: add portal real alarm integration"
```

### Task 2: Expose the new `/api/portal/real-alarms` route without touching `alarm-workorders`

**Files:**
- Modify: `src/qwenpaw/extensions/api/portal_backend.py`
- Modify: `tests/unit/extensions/api/test_portal_backend.py`

- [ ] **Step 1: Write the failing route test**

```python
from fastapi.testclient import TestClient

from qwenpaw.extensions.api import portal_backend


def test_real_alarms_route_returns_backend_payload(monkeypatch) -> None:
    client = TestClient(portal_backend.app)

    monkeypatch.setattr(
        portal_backend,
        "query_portal_real_alarms",
        lambda limit: {
            "total": 1,
            "items": [
                {
                    "id": "mock-deadlock-1",
                    "title": "数据库锁异常",
                    "level": "critical",
                    "status": "active",
                    "eventTime": "2026-04-15 19:20:00",
                    "timeLabel": "2026-04-15 19:20:00",
                    "deviceName": "MySQL",
                    "manageIp": "10.43.150.186",
                    "employeeId": "fault",
                    "dispatchContent": "mysql/死锁 + cmdb/新增/插入",
                    "visibleContent": "数据库锁异常（MySQL 10.43.150.186）",
                }
            ],
            "source": "mock",
        },
    )

    response = client.get("/api/portal/real-alarms?limit=8")

    assert response.status_code == 200
    assert response.json()["source"] == "mock"
    assert response.json()["items"][0]["employeeId"] == "fault"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/extensions/api/test_portal_backend.py -q`

Expected: FAIL with `AttributeError: module 'portal_backend' has no attribute 'query_portal_real_alarms'` or `404 != 200`

- [ ] **Step 3: Write the minimal route implementation**

```python
# src/qwenpaw/extensions/api/portal_backend.py
from qwenpaw.extensions.integrations.portal_real_alarms import query_portal_real_alarms


@router.get("/real-alarms")
async def get_real_alarms(limit: int = 10):
    try:
        return query_portal_real_alarms(limit)
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        print(f"[ERROR] get_real_alarms failed: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/extensions/integrations/test_portal_real_alarms.py tests/unit/extensions/api/test_portal_backend.py -q`

Expected: PASS with the new route covered and the older `alarm-workorders` tests still green

- [ ] **Step 5: Commit**

```bash
git add \
  src/qwenpaw/extensions/api/portal_backend.py \
  tests/unit/extensions/api/test_portal_backend.py
git commit -m "feat: expose portal real alarms route"
```

### Task 3: Add the frontend real-alarm client, mapping helper, and bell polling

**Files:**
- Create: `portal/src/api/portalRealAlarms.ts`
- Create: `portal/src/pages/digital-employee/realAlarms.ts`
- Modify: `portal/src/pages/DigitalEmployeePage.tsx`

- [ ] **Step 1: Write the failing build anchor**

```tsx
// portal/src/pages/digital-employee/realAlarms.ts
import { listPortalRealAlarms } from "../../api/portalRealAlarms";

export async function loadPortalBellAlerts() {
  return listPortalRealAlarms({ limit: 10 });
}
```

```tsx
// portal/src/pages/DigitalEmployeePage.tsx
import { loadPortalBellAlerts } from "./digital-employee/realAlarms";

useEffect(() => {
  void loadPortalBellAlerts();
}, []);
```

- [ ] **Step 2: Run build to verify it fails**

Run: `pnpm --dir portal run build`

Expected: FAIL with `Cannot find module '../../api/portalRealAlarms'`

- [ ] **Step 3: Write the minimal client, mapper, and polling integration**

```ts
// portal/src/api/portalRealAlarms.ts
import { requestPortalApi } from "./portalWorkorders";

export interface PortalRealAlarmItem {
  id: string;
  title: string;
  level: "critical" | "urgent" | "warning" | "info";
  status: "active";
  eventTime: string;
  timeLabel: string;
  deviceName: string;
  manageIp: string;
  employeeId: string;
  dispatchContent: string;
  visibleContent: string;
}

export interface PortalRealAlarmListResponse {
  total: number;
  items: PortalRealAlarmItem[];
  source: "live" | "mock";
}

export async function listPortalRealAlarms(
  params: { limit?: number } = {},
): Promise<PortalRealAlarmListResponse> {
  const searchParams = new URLSearchParams();
  if (params.limit) {
    searchParams.set("limit", String(params.limit));
  }
  return requestPortalApi<PortalRealAlarmListResponse>(
    `/real-alarms${searchParams.toString() ? `?${searchParams.toString()}` : ""}`,
  );
}
```

```ts
// portal/src/pages/digital-employee/realAlarms.ts
import type { PortalRealAlarmItem, PortalRealAlarmListResponse } from "../../api/portalRealAlarms";

export const PORTAL_REAL_ALARM_POLL_INTERVAL_MS = 15000;

type PortalBellAlert = {
  id: string;
  employeeId: string;
  level: "critical" | "urgent" | "warning" | "info";
  message: string;
  timeLabel: string;
  routeEntry?: string | null;
  dispatchContent?: string;
  visibleContent?: string;
};

function toAlertMessage(item: PortalRealAlarmItem) {
  return `${item.title} · ${item.deviceName} · ${item.manageIp}`;
}

export function normalizePortalBellAlerts(
  response: PortalRealAlarmListResponse,
): PortalBellAlert[] {
  const seen = new Set<string>();
  const items = Array.isArray(response.items) ? response.items : [];

  return items
    .filter((item) => {
      if (!item?.id || seen.has(item.id)) {
        return false;
      }
      seen.add(item.id);
      return true;
    })
    .map((item) => ({
      id: item.id,
      employeeId: item.employeeId || "fault",
      level: item.level,
      message: toAlertMessage(item),
      timeLabel: item.timeLabel || item.eventTime,
      routeEntry: null,
      dispatchContent: item.dispatchContent,
      visibleContent: item.visibleContent,
    }));
}
```

```tsx
// portal/src/pages/DigitalEmployeePage.tsx
import { listPortalRealAlarms } from "../api/portalRealAlarms";
import {
  normalizePortalBellAlerts,
  PORTAL_REAL_ALARM_POLL_INTERVAL_MS,
} from "./digital-employee/realAlarms";

const alertPollTimerRef = useRef<number | null>(null);

const loadOpsAlerts = useCallback(async () => {
  try {
    const response = await listPortalRealAlarms({ limit: 10 });
    setOpsAlerts(normalizePortalBellAlerts(response));
  } catch (error) {
    console.error("Failed to load portal real alarms", error);
  }
}, []);

useEffect(() => {
  void loadOpsAlerts();
  alertPollTimerRef.current = window.setInterval(() => {
    void loadOpsAlerts();
  }, PORTAL_REAL_ALARM_POLL_INTERVAL_MS) as unknown as number;

  return () => {
    if (alertPollTimerRef.current) {
      window.clearInterval(alertPollTimerRef.current);
      alertPollTimerRef.current = null;
    }
  };
}, [loadOpsAlerts]);
```

- [ ] **Step 4: Run build to verify it passes**

Run: `pnpm --dir portal run build`

Expected: PASS with the new real-alarm client and page polling compiling cleanly

- [ ] **Step 5: Commit**

```bash
git add \
  portal/src/api/portalRealAlarms.ts \
  portal/src/pages/digital-employee/realAlarms.ts \
  portal/src/pages/DigitalEmployeePage.tsx
git commit -m "feat: poll portal real alarms in alert bell"
```

### Task 4: Run end-to-end regression checks and lock the implementation handoff

**Files:**
- Modify: `tests/unit/extensions/api/test_portal_backend.py`
- Modify: `tests/unit/extensions/integrations/test_portal_real_alarms.py`
- Modify: `portal/src/pages/DigitalEmployeePage.tsx`

- [ ] **Step 1: Add the final regression checks**

```python
def test_real_alarms_route_keeps_alarm_workorders_route_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(portal_backend.app)

    monkeypatch.setattr(
        portal_backend,
        "query_alarm_workorders",
        lambda limit: {"total": 2, "items": [{"id": "wo-1"}], "source": "mock"},
    )
    monkeypatch.setattr(
        portal_backend,
        "query_portal_real_alarms",
        lambda limit: {"total": 1, "items": [{"id": "alarm-1"}], "source": "mock"},
    )

    workorders_response = client.get("/api/portal/alarm-workorders?limit=5")
    real_alarms_response = client.get("/api/portal/real-alarms?limit=5")

    assert workorders_response.status_code == 200
    assert real_alarms_response.status_code == 200
    assert workorders_response.json()["total"] == 2
    assert real_alarms_response.json()["total"] == 1
```

```tsx
// portal/src/pages/DigitalEmployeePage.tsx
// Keep the existing click path unchanged:
// handlePortalAlertAction(alert) removes the alert locally and writes
// pendingPortalDispatch so the fault employee chat receives visibleContent/dispatchContent.
```

- [ ] **Step 2: Run the full verification suite**

Run:

```bash
pytest tests/unit/extensions/integrations/test_portal_real_alarms.py tests/unit/extensions/api/test_portal_backend.py -q
pnpm --dir portal run build
```

Expected: PASS, with the new real-alarm route green, the old `alarm-workorders` route still present, and the portal bundle generated successfully

- [ ] **Step 3: Commit the final integrated change**

```bash
git add \
  src/qwenpaw/extensions/integrations/portal_real_alarms.py \
  src/qwenpaw/extensions/api/portal_backend.py \
  tests/unit/extensions/integrations/test_portal_real_alarms.py \
  tests/unit/extensions/api/test_portal_backend.py \
  deploy-all/qwenpaw/working/workspaces/fault/skills/real-alarm/mock_data.json \
  portal/src/api/portalRealAlarms.ts \
  portal/src/pages/digital-employee/realAlarms.ts \
  portal/src/pages/DigitalEmployeePage.tsx
git commit -m "feat: add portal real alarm polling flow"
```

## Self-Review

### Spec coverage

1. New backend API and helper: Tasks 1-2
2. Gateway live query + last-7-days active request: Task 1
3. Backend mock fallback and mock row: Task 1
4. Portal polling and bell rendering: Task 3
5. Click-to-dispatch into fault diagnosis flow: Task 3
6. Keep `alarm-workorders` unchanged: Tasks 2 and 4

### Placeholder scan

1. No placeholder markers remain.
2. Each task includes exact files, code snippets, commands, and expected outcomes.

### Type consistency

1. Backend route and helper consistently use `query_portal_real_alarms`.
2. Frontend client and page consistently use `PortalRealAlarmListResponse`, `listPortalRealAlarms`, and `normalizePortalBellAlerts`.
3. Click dispatch continues to rely on existing `dispatchContent` and `visibleContent` fields already used by `handlePortalAlertAction`.
