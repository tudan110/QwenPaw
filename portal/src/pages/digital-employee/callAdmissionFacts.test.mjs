import assert from "node:assert/strict";
import test from "node:test";
import { callAdmissionRows, remoteMcpRule } from "./callAdmissionFacts.ts";

const host = { production_guards: true, declared_host_count: 2 };

void test("unknown evidence does not imply host mode or enabled guards", () => {
  assert.equal(remoteMcpRule().mode, "当前状态未知");
  assert.match(callAdmissionRows().find((row) => row.key === "other-apis").mode, /覆盖未确认/);
});

void test("remote MCP distinguishes host, exact, empty and invalid policies", () => {
  assert.match(remoteMcpRule(host).detail, /不区分同主机的不同路径/);
  assert.match(remoteMcpRule({ ...host, endpoint_policy: "exact", declared_endpoint_count: 3 }).mode, /精确白名单 · 3 项/);
  assert.match(remoteMcpRule({ ...host, endpoint_policy: "exact", declared_endpoint_count: 0 }).detail, /拒绝全部远程端点/);
  assert.match(remoteMcpRule({ ...host, endpoint_policy: "invalid" }).detail, /不回退/);
});

void test("inactive guard shows configured rules without claiming enforcement", () => {
  const disabled = { ...host, production_guards: false };
  assert.match(remoteMcpRule(disabled).mode, /^守卫关闭/);
  const invalid = remoteMcpRule({ ...disabled, endpoint_policy: "invalid" });
  assert.match(invalid.mode, /^守卫关闭/);
  assert.match(invalid.detail, /^若开启守卫/);
});

void test("tool classification comes from evidence and is separate from risk levels", () => {
  const rows = callAdmissionRows({
    queried_at: "2026-11-21T01:00:00Z", mcp: host, script_candidates: [],
    tools: [{ name: "read_file", policy: "read_scope" }],
  });
  assert.deepEqual([...new Set(rows.map((row) => row.channel))], ["工具 / Skill", "业务 API", "MCP"]);
  assert.equal(rows[0].mode, "策略分类 · 1 项");
  assert.equal(rows[0].risk, "未逐项分级");
  assert.equal(rows.find((row) => row.key === "cmdb").risk, "待评估");
});
