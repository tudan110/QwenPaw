import assert from "node:assert/strict";
import test from "node:test";
import { previewSensitiveData, reviewExpired, syntheticData, traceChecks } from "./governanceFacts.ts";

void test("trace review distinguishes denied authorization from tool and output outcomes", () => {
  const checks = traceChecks([
    { ts: 1, type: "authorization", decision: "deny", authorization_id: "check-1", target: "CMDB", args: "private input" },
    { ts: 2, type: "tool_call", outcome: "ok", tool_call_id: "call-1", tool_name: "CMDB", result: "private output" },
    { ts: 3, type: "tool_call", outcome: "timeout", tool_name: "inventory" },
    { ts: 4, type: "tool_call", tool_name: "legacy", guard: { severity: "high" } },
    { ts: 5, type: "llm_call", status: "ok" },
    { ts: 6, type: "llm_call", status: "429" },
    { ts: 7, type: "agent_reply", text: "private reply" },
  ]);
  assert.deepEqual(checks.map(({ status, severity }) => [status, severity]), [
    ["已拒绝", "risk"], ["成功", "normal"], ["超时", "risk"], ["未记录结果", "notice"], ["请求状态：429", "risk"],
  ]);
  assert.equal(checks[0].reference, "check-1");
  assert.equal(checks[1].reference, "call-1");
  assert.ok(!JSON.stringify(checks).includes("private"));
});

void test("review date remains valid until the end of its local day", () => {
  const now = new Date(2026, 10, 20, 23, 59);
  assert.equal(reviewExpired("2026-11-19", now), true);
  assert.equal(reviewExpired("2026-11-20", now), false);
  assert.equal(reviewExpired("2026-11-21", now), false);
  assert.equal(reviewExpired("", now), false);
});

void test("synthetic preview masks or removes all sensitive sample fields", () => {
  const omitted = previewSensitiveData("omit");
  assert.deepEqual(omitted, { 资产编号: "DEMO-ASSET-001" });
  const masked = previewSensitiveData("mask");
  for (const key of ["联系人", "电话", "邮箱"]) assert.notEqual(masked[key], syntheticData[key]);
  assert.equal(masked.资产编号, syntheticData.资产编号);
});
