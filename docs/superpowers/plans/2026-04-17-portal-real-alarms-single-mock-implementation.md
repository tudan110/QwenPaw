# Portal Real Alarms Single Mock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/api/portal/real-alarms` return only the `数据库锁异常` row when it falls back to mock data, while leaving the live path and the underlying mock file unchanged.

**Architecture:** Keep the change inside `src/qwenpaw/extensions/integrations/portal_real_alarms.py`. Add a small helper that filters loaded mock rows by exact `alarmtitle`, then reuse the existing normalization/response flow so the route and frontend contract stay unchanged.

**Tech Stack:** Python, httpx, FastAPI route consumer, pytest

---

## File map

- `src/qwenpaw/extensions/integrations/portal_real_alarms.py`
  - Owns live gateway query, mock fallback loading, row normalization, and the response contract for `/api/portal/real-alarms`.
  - Add the deadlock-only mock filter here and apply it only on the mock fallback path.
- `tests/unit/extensions/integrations/test_portal_real_alarms.py`
  - Add regression tests for mixed mock rows and for the no-match mock case.
- `tests/unit/extensions/api/test_portal_backend.py`
  - No code changes planned.
  - Re-run this suite after the helper change to prove the route contract is still unchanged.

### Task 1: Narrow mock fallback to the deadlock row

**Files:**
- Modify: `src/qwenpaw/extensions/integrations/portal_real_alarms.py`
- Modify: `tests/unit/extensions/integrations/test_portal_real_alarms.py`
- Verify: `tests/unit/extensions/api/test_portal_backend.py`

- [ ] **Step 1: Write the failing regression tests**

Add these tests near the existing mock-fallback cases in `tests/unit/extensions/integrations/test_portal_real_alarms.py`:

```python
def test_query_portal_real_alarms_filters_mock_fallback_to_deadlock_row(monkeypatch) -> None:
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._post_real_alarm_list",
        lambda *, limit, begin_time, end_time: {"code": 200, "total": 0, "rows": []},
    )
    monkeypatch.setattr(
        "qwenpaw.extensions.integrations.portal_real_alarms._load_mock_alarm_rows",
        lambda: [
            {
                "alarmuniqueid": "mock-non-deadlock-1",
                "alarmtitle": "端口down",
                "alarmseverity": "2",
                "alarmstatus": "1",
                "eventtime": "2026-04-15 19:10:00",
                "devName": "交换机",
                "manageIp": "10.43.150.100",
            },
            {
                "alarmuniqueid": "mock-deadlock-1",
                "alarmtitle": "数据库锁异常",
                "alarmseverity": "1",
                "alarmstatus": "1",
                "eventtime": "2026-04-15 19:20:00",
                "devName": "MySQL",
                "manageIp": "10.43.150.186",
            },
        ],
    )

    payload = query_portal_real_alarms(limit=10)

    assert payload["source"] == "mock"
    assert payload["total"] == 1
    assert [item["id"] for item in payload["items"]] == ["mock-deadlock-1"]


def test_query_portal_real_alarms_returns_empty_mock_payload_when_filtered_mock_has_no_deadlock_row(
    monkeypatch,
) -> None:
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
                "alarmuniqueid": "mock-non-deadlock-2",
                "alarmtitle": "CPU利用率过高",
                "alarmseverity": "2",
                "alarmstatus": "1",
                "eventtime": "2026-04-15 19:25:00",
                "devName": "k8s-node-01",
                "manageIp": "10.0.0.8",
            }
        ],
    )

    payload = query_portal_real_alarms(limit=10)

    assert payload == {"total": 0, "items": [], "source": "mock"}
```

- [ ] **Step 2: Run the targeted tests and verify they fail for the current behavior**

Run:

```bash
pytest tests/unit/extensions/integrations/test_portal_real_alarms.py::test_query_portal_real_alarms_filters_mock_fallback_to_deadlock_row tests/unit/extensions/integrations/test_portal_real_alarms.py::test_query_portal_real_alarms_returns_empty_mock_payload_when_filtered_mock_has_no_deadlock_row -q
```

Expected:

```text
FAILED tests/unit/extensions/integrations/test_portal_real_alarms.py::test_query_portal_real_alarms_filters_mock_fallback_to_deadlock_row
FAILED tests/unit/extensions/integrations/test_portal_real_alarms.py::test_query_portal_real_alarms_returns_empty_mock_payload_when_filtered_mock_has_no_deadlock_row
```

The current helper loads all mock rows unchanged, so it will still return the non-deadlock rows.

- [ ] **Step 3: Implement the minimal mock-only filter in the backend helper**

Update `src/qwenpaw/extensions/integrations/portal_real_alarms.py` with this focused change:

```python
PORTAL_REAL_ALARM_MOCK_TITLE = "数据库锁异常"


def _filter_portal_mock_alarm_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("alarmtitle") or "").strip() == PORTAL_REAL_ALARM_MOCK_TITLE
    ]


def _load_portal_mock_alarm_rows() -> list[dict[str, Any]]:
    return _filter_portal_mock_alarm_rows(_load_mock_alarm_rows())
```

Then change the two fallback assignments inside `query_portal_real_alarms()` from:

```python
rows = _load_mock_alarm_rows()
```

to:

```python
rows = _load_portal_mock_alarm_rows()
```

Do not change:

```python
rows = list(result.get("rows") or [])
```

on the live path, and do not change `_normalize_alarm_row()` or the route code.

- [ ] **Step 4: Run focused regression coverage**

Run:

```bash
pytest tests/unit/extensions/integrations/test_portal_real_alarms.py tests/unit/extensions/api/test_portal_backend.py -q
```

Expected:

```text
23 passed
```

This proves:

1. mock fallback now returns only the deadlock row,
2. the no-match mock case still returns the empty mock payload,
3. `/api/portal/real-alarms` route behavior stays unchanged.

- [ ] **Step 5: Commit the change**

Run:

```bash
git add src/qwenpaw/extensions/integrations/portal_real_alarms.py tests/unit/extensions/integrations/test_portal_real_alarms.py
git commit -m "fix: narrow portal real alarm mock fallback

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```
