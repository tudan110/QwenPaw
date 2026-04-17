# Portal real alarms single mock fallback design

## Problem

`/api/portal/real-alarms` currently falls back to all rows from `deploy-all/qwenpaw/working/workspaces/fault/skills/real-alarm/mock_data.json` when the live gateway query fails or returns no rows.

For the current portal fault demo, the user only wants the backend mock fallback of `/api/portal/real-alarms` to return the database deadlock alarm (`数据库锁异常`), while preserving the rest of the mock file for other scenarios.

## Scope

### In scope

1. Change the portal real-alarms backend helper so mock fallback returns only the `数据库锁异常` row.
2. Add regression coverage for the new mock filtering behavior.

### Out of scope

1. Editing `mock_data.json` to remove other rows.
2. Changing the `real-alarm` skill itself.
3. Changing `/api/portal/alarm-workorders`.
4. Changing portal frontend polling or bell rendering.
5. Changing live gateway results.

## Goals

1. Keep `mock_data.json` intact for non-portal scenarios.
2. Make `/api/portal/real-alarms` return only the deadlock mock row when it falls back to mock data.
3. Leave live query behavior unchanged.

## Architecture

This change stays entirely inside the dedicated portal real-alarms backend helper:

1. `query_portal_real_alarms()` still queries the live gateway first.
2. If the live query fails or returns no rows, the helper still loads mock rows from `mock_data.json`.
3. Before normalization, the helper filters mock rows to only those whose `alarmtitle` is `数据库锁异常`.
4. The route and frontend keep consuming the same response contract as before.

No new route, config, or frontend code is needed.

## Data flow

### Live path

The live path is unchanged:

1. Query `http://gateway:30080/resource/realalarm/list`.
2. If live rows are present, return them as-is after existing normalization.

### Mock path

The mock path changes as follows:

1. Load `rows` from `deploy-all/qwenpaw/working/workspaces/fault/skills/real-alarm/mock_data.json`.
2. Keep only rows where `alarmtitle == "数据库锁异常"`.
3. Normalize the filtered rows into the existing portal alert payload.
4. Return `source: "mock"` with only the filtered items.

If no matching mock row exists, return the existing empty mock response shape:

```json
{
  "total": 0,
  "items": [],
  "source": "mock"
}
```

## Error handling

1. Do not change how live request errors are handled.
2. Do not raise a new error when the mock file contains no matching deadlock row.
3. Keep the current empty mock response behavior for missing file or no matching row.

## Testing

Add backend regression coverage for:

1. Mock fallback with multiple rows only returns the `数据库锁异常` row.
2. Mock fallback still returns an empty mock payload when no deadlock row is present.
3. Existing live-path tests remain unchanged and green.

## Implementation notes

1. Keep the filtering logic inside `src/qwenpaw/extensions/integrations/portal_real_alarms.py`.
2. Prefer a small helper for readability if that makes the file clearer, but do not refactor unrelated logic.
3. Match titles exactly against `数据库锁异常` for this scoped demo requirement.
