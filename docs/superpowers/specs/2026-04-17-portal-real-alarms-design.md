# Portal real alarms polling design

## Problem

The portal top-right alert bell needs its own real-alarm flow for the fault digital employee scenario. The existing `/api/portal/alarm-workorders` route is owned by a different demo path and must remain unchanged.

The new flow must:

1. Query the ZhiGuan real-alarm API through backend code.
2. Show active alarms in the portal alert bell.
3. Let the user click one alarm and send it to the fault digital employee as the next conversation input.
4. Reuse the existing fault diagnosis and root-cause analysis flow after that click.
5. Return backend mock alarm data during development when the live query fails or returns no active alarms.

## Scope

### In scope

1. A new backend portal API dedicated to real alarms.
2. Backend live query to `http://gateway:30080/resource/realalarm/list`.
3. Backend normalization from ZhiGuan alarm rows into a portal alert payload.
4. Backend mock fallback for development.
5. Portal polling for the new route.
6. Portal bell rendering from the new route.
7. Click-to-dispatch from bell alert to the fault employee chat.
8. Adding a database deadlock alarm row to the real-alarm mock dataset.

### Out of scope

1. Modifying `/api/portal/alarm-workorders` or the alarm workbench demo flow.
2. Alarm clear APIs.
3. Workorder status update APIs.
4. Recovery notification callbacks.
5. Full alarm-to-workorder closed loop.

## Goals

1. Keep the alarm bell path isolated from the alarm-workorders demo path.
2. Make the fault employee bell show live active alarms from the last 7 days.
3. Preserve useful bell behavior during development even when the gateway side is not ready.
4. Ensure clicking a bell alert enters the already-implemented fault diagnosis path with no duplicate business logic in the UI.

## Architecture

### Backend

Add a new route under `src/qwenpaw/extensions/api/portal_backend.py`:

- `GET /api/portal/real-alarms`

This route owns the portal bell real-alarm use case and does not reuse the workorder route shape.

The route will:

1. Call the ZhiGuan API at `http://gateway:30080/resource/realalarm/list`.
2. Send a fixed query for active alarms (`alarmstatus=1`) from the last 7 days.
3. Normalize the response rows into a portal-focused alert payload.
4. Return backend mock data when the live query errors, times out, or returns no rows during the current development stage.

To keep responsibilities clear, the implementation should live in a new backend helper module dedicated to portal real alarms instead of extending the current alarm-workorders bridge.

### Frontend

Add a new portal API client for `/portal-api/real-alarms`.

`DigitalEmployeePage.tsx` will use this new route to populate `opsAlerts`. The current alert bell UI stays in place, but its data source becomes the new real-alarm polling flow.

The click behavior stays aligned with the current portal interaction pattern:

1. User opens the bell.
2. User clicks a specific alarm.
3. Portal closes the popup and removes that alert from the local visible reminder list.
4. Portal dispatches the alert into the fault employee conversation using the payload returned by backend.
5. The existing fault diagnosis and root-cause analysis path handles the rest.

## Backend contract

The new route returns a portal-specific payload:

```json
{
  "total": 1,
  "items": [
    {
      "id": "COMMON__1776338881568_2044739586778116096",
      "title": "数据库锁异常",
      "level": "critical",
      "status": "active",
      "eventTime": "2026-04-15 19:20:00",
      "timeLabel": "2026-04-15 19:20:00",
      "deviceName": "MySQL",
      "manageIp": "10.43.150.186",
      "employeeId": "fault",
      "dispatchContent": "mysql/死锁 + cmdb/新增/插入",
      "visibleContent": "数据库锁异常（MySQL 10.43.150.186）"
    }
  ],
  "source": "live"
}
```

### Field rules

1. `id` comes from `alarmuniqueid`.
2. `title` comes from `alarmtitle`.
3. `level` is mapped from `alarmseverity` into portal bell severities:
   - `1` -> `critical`
   - `2` -> `urgent`
   - `3` -> `warning`
   - other values -> `info`
4. `status` is fixed to `active` because this route only returns active alarms.
5. `eventTime` and `timeLabel` are derived from the source event time.
6. `employeeId` is fixed to `fault`.
7. `dispatchContent` is the actual prompt sent to the fault employee when the alert is clicked.
8. `visibleContent` is the human-readable text shown as the user message in chat.
9. `source` is `live` or `mock` for troubleshooting and development visibility.

## Live query behavior

The backend sends this logical request to ZhiGuan:

```json
{
  "pageNum": 1,
  "pageSize": 10,
  "alarmseverity": "",
  "alarmstatus": "1",
  "params": {
    "beginEventtime": "<now - 7 days>",
    "endEventtime": "<now>"
  }
}
```

Implementation notes:

1. The gateway base URL is `http://gateway:30080`.
2. The route should expose an optional `limit` query param for portal use, while still enforcing a sane minimum and maximum.
3. The backend should own request timeout behavior so the frontend does not need to know ZhiGuan specifics.
4. The backend should return normalized portal alerts, not raw ZhiGuan rows.

## Mock behavior

During the current development stage, backend mock fallback is part of the contract.

### Trigger conditions

The new backend route returns mock data when any of the following happens:

1. The live request errors.
2. The live request times out.
3. The live request succeeds but returns no active alarms.

### Mock source

The canonical raw mock row lives in:

- `deploy-all/qwenpaw/working/workspaces/fault/skills/real-alarm/mock_data.json`

Add one new row for a database deadlock alarm based on the user-provided sample and aligned with the existing mock file structure.

The new route may read from that file directly or through a small dedicated helper, but it must normalize the mock row into the same portal alert payload as live rows.

### Required deadlock mock content

The new mock entry must represent a MySQL deadlock-style active alarm and include at least:

1. `alarmtitle`: `数据库锁异常`
2. `devName`: `MySQL`
3. `manageIp`: `10.43.150.186`
4. `alarmstatus`: active
5. `alarmseverity`: highest severity
6. A stable `alarmuniqueid`

The normalized portal payload for this row must map to:

1. `level: "critical"`
2. `employeeId: "fault"`
3. `dispatchContent: "mysql/死锁 + cmdb/新增/插入"`
4. `visibleContent` that clearly identifies the deadlock alarm in chat

## Portal bell behavior

### Polling

The portal starts polling the new `/portal-api/real-alarms` route when the page is active.

Polling requirements:

1. Fetch on initial load.
2. Continue on a fixed interval suitable for dashboard reminders.
3. Clean up timers on unmount.
4. Keep the last successful result if a later poll fails, so the bell does not flicker empty because of a transient backend issue.

### Rendering

`opsAlerts` becomes the normalized result of the new real-alarm API.

Requirements:

1. Use `id` as the alert identity key.
2. Deduplicate by `id`.
3. Sort by existing bell severity order.
4. Keep the existing bell popup and toast mechanics.

### Click behavior

When a user clicks an alert in the bell:

1. Close the popup.
2. Remove the clicked alert from the current frontend reminder list.
3. Navigate to or focus the fault digital employee if needed.
4. Send `dispatchContent` into the existing fault chat send flow.
5. Show `visibleContent` as the visible user message.

The click action does not clear the upstream alarm in ZhiGuan. It only consumes the reminder in the local portal session. If a later poll sees the same active alarm again, it may reappear in the bell.

## Error handling

1. Do not change the existing `alarm-workorders` implementation or route behavior.
2. Do not silently swallow backend fetch failures; log or surface them using the project's existing patterns.
3. Frontend polling failure should not wipe a previously successful alert list.
4. Mock fallback must preserve the same response shape as live data.
5. If the backend returns an empty normalized list after all fallback logic, the bell simply shows no alerts.

## Testing strategy

### Backend

Add route and normalization coverage for:

1. Live payload normalization into the portal alert contract.
2. Mock fallback on request failure.
3. Mock fallback on live empty rows.
4. Severity mapping.
5. Last-7-days request shape.
6. Separation from the existing `/alarm-workorders` route.

### Frontend

Add focused tests for:

1. New API client response handling.
2. Poll result normalization into `opsAlerts`.
3. Clicking a bell alert dispatches the expected content to the fault employee flow.
4. Duplicate alert IDs do not create duplicate bell entries.
5. Poll failures keep the last successful alert list.

### Manual verification

The final implementation is correct when:

1. Live gateway data appears in the bell when active alarms exist.
2. The deadlock mock alarm appears when live data is unavailable or empty in development.
3. Clicking the bell alert starts the fault employee conversation with the expected visible and dispatch content.
4. The existing alarm-workorders demo remains unchanged.

## Implementation notes

1. Prefer a new backend integration/helper module for portal real alarms rather than adding more responsibilities to `query_alarm_workorders.py`.
2. Reuse existing portal request helpers where appropriate, but keep the real-alarm client separate from workorder naming.
3. Reuse the current fault dispatch path in `DigitalEmployeePage.tsx` instead of creating a second diagnosis entry path.
