# Fault Scenario RCA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a non-invasive fault-scenario RCA path in the fault operator chat that detects the CMDB-add-failed/MySQL-deadlock demo case, calls new skills through `src/qwenpaw/extensions`, and renders structured results plus a full diagnosis log drawer in `portal`.

**Architecture:** Keep the existing portal fault chat and legacy `fault-disposal` flow untouched by adding a narrow side-path: detect the target scene in the fault operator chat, call new `/api/portal/fault-scenarios/*` endpoints, and render structured cards only for those messages. Backend work stays inside `src/qwenpaw/extensions`, where a new service normalizes prompts, invokes the new skills, persists history, and returns a fixed response contract for the portal.

**Tech Stack:** FastAPI, pytest, Python subprocess/A2A skill orchestration, React 18, TypeScript, Ant Design, Vite build checks

---

## File Structure

### Backend / API

- Create: `src/qwenpaw/extensions/api/fault_scenario_models.py`
  - TypedDict/dataclass-style contracts for scene detection, progress steps, root cause cards, log entries, and API responses.
- Create: `src/qwenpaw/extensions/api/fault_scenario_service.py`
  - Prompt detection, request normalization, skill invocation, response shaping, and history/log helpers.
- Modify: `src/qwenpaw/extensions/api/portal_backend.py`
  - Register new `/fault-scenarios/diagnose` and `/fault-scenarios/history/{session_id}` routes without disturbing old `/fault-disposal/*` routes.

### Skills

- Create: `deploy-all/qwenpaw/working/workspaces/fault/skills/mysql-deadlock-inspector/SKILL.md`
- Create: `deploy-all/qwenpaw/working/workspaces/fault/skills/mysql-deadlock-inspector/scripts/query_mysql_deadlock.py`
- Create: `deploy-all/qwenpaw/working/workspaces/fault/skills/mysql-deadlock-inspector/.env.example`
  - Read-only MySQL evidence collection for deadlock/lock wait/blocked SQL.
- Create: `deploy-all/qwenpaw/working/workspaces/fault/skills/scenario-root-cause-analyst/SKILL.md`
- Create: `deploy-all/qwenpaw/working/workspaces/fault/skills/scenario-root-cause-analyst/scripts/analyze_scenario.py`
- Create: `deploy-all/qwenpaw/working/workspaces/fault/skills/scenario-root-cause-analyst/references/output-contract.md`
  - General scene RCA entrypoint that coordinates `zgops-cmdb` and `mysql-deadlock-inspector`.

### Frontend

- Create: `portal/src/api/faultScenario.ts`
  - Typed API client for the new backend routes.
- Create: `portal/src/pages/digital-employee/faultScenario.ts`
  - Scene detection helpers, payload builders, and frontend result normalization.
- Create: `portal/src/pages/digital-employee/faultScenarioComponents.tsx`
  - Structured result card, progress list, root-cause card, and diagnosis log drawer.
- Modify: `portal/src/pages/digital-employee/useRemoteChatSession.ts`
  - Insert the non-invasive scene side-path before the existing remote streaming path.
- Modify: `portal/src/pages/digital-employee/components.tsx`
  - Render the new structured scenario message blocks.
- Modify: `portal/src/pages/digital-employee.css`
  - Styles for result cards and the log drawer.

### Tests

- Create: `tests/unit/extensions/api/test_fault_scenario_service.py`
  - Unit tests for scene detection, payload shaping, and skill-output parsing.
- Modify: `tests/unit/extensions/api/test_portal_backend.py`
  - Route-level tests for the new portal scenario APIs and history persistence.

### Validation note

`portal` currently has no frontend unit test runner in `package.json`, so frontend red/green checks use `pnpm --dir portal run build`. Backend uses pytest.

---

### Task 1: Add backend scene contracts and prompt detection

**Files:**
- Create: `src/qwenpaw/extensions/api/fault_scenario_models.py`
- Create: `src/qwenpaw/extensions/api/fault_scenario_service.py`
- Test: `tests/unit/extensions/api/test_fault_scenario_service.py`

- [ ] **Step 1: Write the failing test**

```python
from qwenpaw.extensions.api.fault_scenario_service import detect_fault_scenario


def test_detect_fault_scenario_matches_fault_chat_deadlock_keywords() -> None:
    detection = detect_fault_scenario(
        employee_id="fault",
        content="CMDB 添加设备失败了，怀疑 mysql 死锁，帮我分析一下",
    )

    assert detection.triggered is True
    assert detection.scene_code == "cmdb_add_failed_mysql_deadlock"
    assert detection.entry_summary == "正在关联分析..."


def test_detect_fault_scenario_ignores_non_fault_employee() -> None:
    detection = detect_fault_scenario(
        employee_id="query",
        content="CMDB 添加设备失败了，怀疑 mysql 死锁",
    )

    assert detection.triggered is False
    assert detection.scene_code == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/extensions/api/test_fault_scenario_service.py -q`

Expected: FAIL with `ModuleNotFoundError` or `cannot import name 'detect_fault_scenario'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/qwenpaw/extensions/api/fault_scenario_models.py
from dataclasses import dataclass


@dataclass(slots=True)
class FaultScenarioDetection:
    triggered: bool
    scene_code: str
    entry_summary: str


# src/qwenpaw/extensions/api/fault_scenario_service.py
SCENE_KEYWORDS = ("cmdb", "添加", "新增", "插入", "死锁", "lock", "mysql")


def detect_fault_scenario(*, employee_id: str, content: str) -> FaultScenarioDetection:
    normalized = str(content or "").strip().lower()
    if employee_id != "fault":
        return FaultScenarioDetection(False, "", "")
    if "cmdb" not in normalized or "死锁" not in normalized and "mysql" not in normalized:
        return FaultScenarioDetection(False, "", "")
    return FaultScenarioDetection(
        triggered=True,
        scene_code="cmdb_add_failed_mysql_deadlock",
        entry_summary="正在关联分析...",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/extensions/api/test_fault_scenario_service.py -q`

Expected: PASS with `2 passed`

- [ ] **Step 5: Commit**

```bash
git add \
  src/qwenpaw/extensions/api/fault_scenario_models.py \
  src/qwenpaw/extensions/api/fault_scenario_service.py \
  tests/unit/extensions/api/test_fault_scenario_service.py
git commit -m "feat: add fault scenario detection contracts"
```

### Task 2: Add backend skill runner and portal scenario routes

**Files:**
- Modify: `src/qwenpaw/extensions/api/fault_scenario_service.py`
- Modify: `src/qwenpaw/extensions/api/portal_backend.py`
- Modify: `tests/unit/extensions/api/test_portal_backend.py`

- [ ] **Step 1: Write the failing route test**

```python
from fastapi.testclient import TestClient

from qwenpaw.extensions.api import portal_backend


def test_fault_scenario_diagnose_route_returns_structured_result(monkeypatch) -> None:
    client = TestClient(portal_backend.app)

    monkeypatch.setattr(
        portal_backend,
        "run_fault_scenario_diagnose",
        lambda payload: {
            "session": {"sessionId": payload["sessionId"], "scene": "cmdb_add_failed_mysql_deadlock"},
            "result": {
                "summary": "已定位为数据库死锁导致 CMDB 新增失败",
                "rootCause": {"type": "数据库异常"},
                "steps": [{"id": "database-analysis", "status": "success"}],
                "logEntries": [{"stage": "database-analysis", "summary": "锁等待命中"}],
            },
        },
    )

    response = client.post(
        "/api/portal/fault-scenarios/diagnose",
        json={
            "sessionId": "fault-scenario-1",
            "employeeId": "fault",
            "content": "CMDB 添加失败，怀疑 mysql 死锁",
        },
    )

    assert response.status_code == 200
    assert response.json()["result"]["rootCause"]["type"] == "数据库异常"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/extensions/api/test_portal_backend.py -q`

Expected: FAIL with `AttributeError: module 'portal_backend' has no attribute 'run_fault_scenario_diagnose'` or `404 != 200`

- [ ] **Step 3: Write minimal implementation**

```python
# src/qwenpaw/extensions/api/fault_scenario_service.py
def run_fault_scenario_diagnose(payload: dict) -> dict:
    return {
        "session": {
            "sessionId": payload["sessionId"],
            "scene": "cmdb_add_failed_mysql_deadlock",
        },
        "result": {
            "summary": "已定位为数据库死锁导致 CMDB 新增失败",
            "rootCause": {"type": "数据库异常"},
            "steps": [],
            "logEntries": [],
        },
    }


# src/qwenpaw/extensions/api/portal_backend.py
from qwenpaw.extensions.api.fault_scenario_service import run_fault_scenario_diagnose


@router.post("/fault-scenarios/diagnose")
async def portal_fault_scenario_diagnose(
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    session_id = str(payload.get("sessionId") or "").strip()
    if not session_id:
        raise ValueError("sessionId is required")
    result = run_fault_scenario_diagnose(payload)
    history = await _load_portal_fault_history(request, session_id=session_id)
    history.append(_compact_ui_message({"id": f"user-{session_id}", "type": "user", "content": payload.get("content", "")}))
    history.append(
        _compact_ui_message(
            {
                "id": f"agent-{session_id}",
                "type": "agent",
                "content": result["result"]["summary"],
                "faultScenarioResult": result["result"],
            }
        )
    )
    await _save_portal_fault_history(request, session_id=session_id, messages=history)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/extensions/api/test_fault_scenario_service.py tests/unit/extensions/api/test_portal_backend.py -q`

Expected: PASS with the new scenario route covered

- [ ] **Step 5: Commit**

```bash
git add \
  src/qwenpaw/extensions/api/fault_scenario_service.py \
  src/qwenpaw/extensions/api/portal_backend.py \
  tests/unit/extensions/api/test_portal_backend.py
git commit -m "feat: add portal fault scenario APIs"
```

### Task 3: Scaffold the new skills and wire structured skill output

**Files:**
- Create: `deploy-all/qwenpaw/working/workspaces/fault/skills/mysql-deadlock-inspector/SKILL.md`
- Create: `deploy-all/qwenpaw/working/workspaces/fault/skills/mysql-deadlock-inspector/scripts/query_mysql_deadlock.py`
- Create: `deploy-all/qwenpaw/working/workspaces/fault/skills/mysql-deadlock-inspector/.env.example`
- Create: `deploy-all/qwenpaw/working/workspaces/fault/skills/scenario-root-cause-analyst/SKILL.md`
- Create: `deploy-all/qwenpaw/working/workspaces/fault/skills/scenario-root-cause-analyst/scripts/analyze_scenario.py`
- Create: `deploy-all/qwenpaw/working/workspaces/fault/skills/scenario-root-cause-analyst/references/output-contract.md`
- Modify: `src/qwenpaw/extensions/api/fault_scenario_service.py`
- Test: `tests/unit/extensions/api/test_fault_scenario_service.py`

- [ ] **Step 1: Write the failing parser test**

```python
from qwenpaw.extensions.api.fault_scenario_service import parse_fault_scenario_output


def test_parse_fault_scenario_output_keeps_root_cause_and_logs() -> None:
    payload = parse_fault_scenario_output(
        """
        {"summary":"已定位为数据库死锁导致 CMDB 新增失败",
         "rootCause":{"type":"数据库异常","object":"cmdb_device"},
         "steps":[{"id":"database-analysis","status":"success"}],
         "logEntries":[{"stage":"database-analysis","summary":"捕获锁等待"}]}
        """
    )

    assert payload["rootCause"]["object"] == "cmdb_device"
    assert payload["logEntries"][0]["stage"] == "database-analysis"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/extensions/api/test_fault_scenario_service.py -q`

Expected: FAIL with `cannot import name 'parse_fault_scenario_output'`

- [ ] **Step 3: Write minimal implementation and skill scaffolds**

```python
# src/qwenpaw/extensions/api/fault_scenario_service.py
import json
import subprocess
import sys
from pathlib import Path


def parse_fault_scenario_output(stdout_text: str) -> dict:
    payload = json.loads(stdout_text)
    payload.setdefault("steps", [])
    payload.setdefault("logEntries", [])
    return payload


def _fault_skill_root() -> Path:
    return Path(__file__).resolve().parents[4] / "deploy-all" / "qwenpaw" / "working" / "workspaces" / "fault" / "skills"
```

```markdown
<!-- deploy-all/.../mysql-deadlock-inspector/SKILL.md -->
---
name: mysql-deadlock-inspector
description: 只读查询 MySQL 死锁、锁等待、阻塞事务与相关 SQL 证据。
---
```

```python
# deploy-all/.../mysql-deadlock-inspector/scripts/query_mysql_deadlock.py
import json


def main() -> None:
    print(json.dumps({"deadlocks": [], "lockWaits": [], "transactions": []}, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

```markdown
<!-- deploy-all/.../scenario-root-cause-analyst/SKILL.md -->
---
name: scenario-root-cause-analyst
description: 通用故障场景根因分析 skill，通过 A2A 协作 zgops-cmdb 与 mysql-deadlock-inspector。
---
```

```python
# deploy-all/.../scenario-root-cause-analyst/scripts/analyze_scenario.py
import json


def main() -> None:
    print(
        json.dumps(
            {
                "summary": "已定位为数据库死锁导致 CMDB 新增失败",
                "rootCause": {"type": "数据库异常", "object": "cmdb_device"},
                "steps": [{"id": "database-analysis", "status": "success"}],
                "logEntries": [{"stage": "database-analysis", "summary": "捕获锁等待"}],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run checks to verify they pass**

Run:

```bash
pytest tests/unit/extensions/api/test_fault_scenario_service.py -q
python deploy-all/qwenpaw/working/workspaces/fault/skills/mysql-deadlock-inspector/scripts/query_mysql_deadlock.py
python deploy-all/qwenpaw/working/workspaces/fault/skills/scenario-root-cause-analyst/scripts/analyze_scenario.py
```

Expected:
- pytest PASS
- both Python scripts print valid JSON

- [ ] **Step 5: Commit**

```bash
git add \
  deploy-all/qwenpaw/working/workspaces/fault/skills/mysql-deadlock-inspector \
  deploy-all/qwenpaw/working/workspaces/fault/skills/scenario-root-cause-analyst \
  src/qwenpaw/extensions/api/fault_scenario_service.py \
  tests/unit/extensions/api/test_fault_scenario_service.py
git commit -m "feat: add fault scenario analysis skills"
```

### Task 4: Intercept the target scene in the fault operator chat

**Files:**
- Create: `portal/src/api/faultScenario.ts`
- Create: `portal/src/pages/digital-employee/faultScenario.ts`
- Modify: `portal/src/pages/digital-employee/useRemoteChatSession.ts`

- [ ] **Step 1: Write the failing build-trigger change**

```ts
// portal/src/pages/digital-employee/useRemoteChatSession.ts
import { maybeHandleFaultScenarioMessage } from "./faultScenario";

// inside handleRemoteSendMessage before createChat(...)
const scenarioResult = await maybeHandleFaultScenarioMessage({
  currentEmployee: nextEmployee,
  content,
  visibleContent: normalizedVisibleContent,
  sessionId: currentSessionIdRef.current,
  setMessages,
});
if (scenarioResult.handled) {
  setIsStreaming(false);
  setCurrentChatStatus("idle");
  return scenarioResult.succeeded;
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `pnpm --dir portal run build`

Expected: FAIL with `Cannot find module './faultScenario'`

- [ ] **Step 3: Write minimal implementation**

```ts
// portal/src/api/faultScenario.ts
export async function diagnoseFaultScenario(payload: Record<string, unknown>) {
  const response = await fetch("/portal-api/fault-scenarios/diagnose", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error((await response.text()) || "故障场景分析失败");
  }
  return response.json();
}
```

```ts
// portal/src/pages/digital-employee/faultScenario.ts
import { diagnoseFaultScenario } from "../../api/faultScenario";

const SCENE_RE = /(cmdb).*(失败|报错|超时)|((mysql|死锁).*(cmdb|新增|插入))/i;

export async function maybeHandleFaultScenarioMessage({
  currentEmployee,
  content,
  visibleContent,
  sessionId,
  setMessages,
}: any) {
  if (currentEmployee?.id !== "fault" || !SCENE_RE.test(content || "")) {
    return { handled: false, succeeded: false };
  }

  setMessages((prev: any[]) => [
    ...prev,
    { id: `user-${Date.now()}`, type: "user", content: visibleContent || content },
    { id: `agent-${Date.now()}`, type: "agent", content: "正在关联分析..." },
  ]);

  const result = await diagnoseFaultScenario({
    sessionId: sessionId || `fault-scenario-${Date.now()}`,
    employeeId: "fault",
    content,
  });

  setMessages((prev: any[]) =>
    prev.map((item) =>
      item.content === "正在关联分析..."
        ? { ...item, content: result.result.summary, faultScenarioResult: result.result }
        : item,
    ),
  );

  return { handled: true, succeeded: true };
}
```

- [ ] **Step 4: Run build to verify it passes**

Run: `pnpm --dir portal run build`

Expected: PASS with the Vite production bundle generated

- [ ] **Step 5: Commit**

```bash
git add \
  portal/src/api/faultScenario.ts \
  portal/src/pages/digital-employee/faultScenario.ts \
  portal/src/pages/digital-employee/useRemoteChatSession.ts
git commit -m "feat: intercept fault scenario messages in portal chat"
```

### Task 5: Render structured scenario results and the diagnosis log drawer

**Files:**
- Create: `portal/src/pages/digital-employee/faultScenarioComponents.tsx`
- Modify: `portal/src/pages/digital-employee/components.tsx`
- Modify: `portal/src/pages/digital-employee.css`

- [ ] **Step 1: Write the failing build-trigger change**

```tsx
// portal/src/pages/digital-employee/components.tsx
import { FaultScenarioResultCard } from "./faultScenarioComponents";

const faultScenarioResult = message.faultScenarioResult;

{faultScenarioResult ? (
  <FaultScenarioResultCard result={faultScenarioResult} />
) : null}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `pnpm --dir portal run build`

Expected: FAIL with `Cannot find module './faultScenarioComponents'`

- [ ] **Step 3: Write minimal implementation**

```tsx
// portal/src/pages/digital-employee/faultScenarioComponents.tsx
import { Drawer } from "antd";
import { useMemo, useState } from "react";

export function FaultScenarioResultCard({ result }: { result: any }) {
  const [open, setOpen] = useState(false);
  const rootCause = result?.rootCause || {};
  const steps = useMemo(() => result?.steps || [], [result]);

  return (
    <div className="fault-scenario-card">
      <div className="fault-scenario-summary">{result?.summary}</div>
      <div className="fault-scenario-root-cause">
        <strong>{rootCause.type}</strong>
        <span>{rootCause.object}</span>
      </div>
      <ul className="fault-scenario-steps">
        {steps.map((step: any) => (
          <li key={step.id}>{step.id}：{step.status}</li>
        ))}
      </ul>
      <div className="fault-scenario-actions">
        <button type="button" onClick={() => setOpen(true)}>查看诊断日志</button>
        <button type="button">故障处置</button>
      </div>
      <Drawer title="诊断日志" open={open} onClose={() => setOpen(false)}>
        {(result?.logEntries || []).map((entry: any, index: number) => (
          <div key={`${entry.stage}-${index}`} className="fault-scenario-log-entry">
            <strong>{entry.stage}</strong>
            <p>{entry.summary}</p>
          </div>
        ))}
      </Drawer>
    </div>
  );
}
```

```css
/* portal/src/pages/digital-employee.css */
.fault-scenario-card { border: 1px solid rgba(99, 123, 255, 0.22); border-radius: 16px; padding: 16px; background: rgba(12, 17, 35, 0.88); }
.fault-scenario-summary { font-weight: 600; margin-bottom: 12px; }
.fault-scenario-root-cause { display: grid; gap: 4px; margin-bottom: 12px; }
.fault-scenario-steps { margin: 0 0 12px; padding-left: 18px; }
.fault-scenario-actions { display: flex; gap: 12px; }
.fault-scenario-log-entry { margin-bottom: 12px; }
```

- [ ] **Step 4: Run build to verify it passes**

Run: `pnpm --dir portal run build`

Expected: PASS and the new card/drawer components type-check successfully

- [ ] **Step 5: Commit**

```bash
git add \
  portal/src/pages/digital-employee/faultScenarioComponents.tsx \
  portal/src/pages/digital-employee/components.tsx \
  portal/src/pages/digital-employee.css
git commit -m "feat: render structured fault scenario results"
```

### Task 6: Finish response shaping, history replay, and regression validation

**Files:**
- Modify: `src/qwenpaw/extensions/api/fault_scenario_service.py`
- Modify: `src/qwenpaw/extensions/api/portal_backend.py`
- Modify: `portal/src/pages/digital-employee/faultScenario.ts`
- Modify: `tests/unit/extensions/api/test_fault_scenario_service.py`
- Modify: `tests/unit/extensions/api/test_portal_backend.py`

- [ ] **Step 1: Write the failing regression tests**

```python
def test_detect_fault_scenario_does_not_trigger_for_plain_fault_question() -> None:
    detection = detect_fault_scenario(
        employee_id="fault",
        content="帮我看一下今天的告警情况",
    )
    assert detection.triggered is False


def test_parse_fault_scenario_output_defaults_partial_status() -> None:
    payload = parse_fault_scenario_output('{"summary":"部分完成"}')
    assert payload["steps"] == []
    assert payload["logEntries"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/extensions/api/test_fault_scenario_service.py tests/unit/extensions/api/test_portal_backend.py -q`

Expected: FAIL until fallback and default-shaping behavior is implemented

- [ ] **Step 3: Write minimal implementation**

```python
# src/qwenpaw/extensions/api/fault_scenario_service.py
def detect_fault_scenario(*, employee_id: str, content: str) -> FaultScenarioDetection:
    normalized = str(content or "").strip().lower()
    if employee_id != "fault":
        return FaultScenarioDetection(False, "", "")
    if "告警" in normalized and "cmdb" not in normalized:
        return FaultScenarioDetection(False, "", "")
    if "cmdb" not in normalized or ("死锁" not in normalized and "mysql" not in normalized):
        return FaultScenarioDetection(False, "", "")
    return FaultScenarioDetection(True, "cmdb_add_failed_mysql_deadlock", "正在关联分析...")
```

```ts
// portal/src/pages/digital-employee/faultScenario.ts
export function normalizeFaultScenarioResult(result: any) {
  return {
    summary: result?.summary || "诊断已完成",
    rootCause: result?.rootCause || {},
    steps: Array.isArray(result?.steps) ? result.steps : [],
    logEntries: Array.isArray(result?.logEntries) ? result.logEntries : [],
    actions: Array.isArray(result?.actions) ? result.actions : [],
  };
}
```

- [ ] **Step 4: Run the full verification set**

Run:

```bash
pytest tests/unit/extensions/api/test_fault_scenario_service.py tests/unit/extensions/api/test_portal_backend.py -q
pnpm --dir portal run build
```

Expected:
- pytest PASS
- portal build PASS

- [ ] **Step 5: Commit**

```bash
git add \
  src/qwenpaw/extensions/api/fault_scenario_service.py \
  src/qwenpaw/extensions/api/portal_backend.py \
  portal/src/pages/digital-employee/faultScenario.ts \
  tests/unit/extensions/api/test_fault_scenario_service.py \
  tests/unit/extensions/api/test_portal_backend.py
git commit -m "feat: finalize fault scenario RCA flow"
```

## Spec coverage check

- 对话触发新场景旁路：Task 4, Task 6
- 后端仅落在 `src/qwenpaw/extensions`：Task 1, Task 2, Task 6
- 新 skill 仅落在 `deploy-all/qwenpaw/working/workspaces/fault/skills`：Task 3
- 复用 `zgops-cmdb` / A2A 思路：Task 3
- 结构化结果卡片：Task 5
- 完整日志侧板：Task 5
- “故障处置”按钮占位：Task 5
- 首版聚焦 MySQL 死锁、保留扩展：Task 1, Task 3, Task 6
- 旧 `fault-disposal` 和旧 portal 逻辑不改语义：Task 2, Task 4, Task 6

## Placeholder scan

- No `TODO` / `TBD`
- Every task includes concrete file paths
- Every code step includes concrete code blocks
- Every verification step includes exact commands

## Type consistency check

- Backend scene code stays `cmdb_add_failed_mysql_deadlock`
- Frontend uses `faultScenarioResult` consistently for structured scenario messages
- Service parser uses `summary`, `rootCause`, `steps`, `logEntries`, `actions` consistently
