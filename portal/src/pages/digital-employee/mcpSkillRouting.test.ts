import assert from "node:assert/strict";
import test from "node:test";
// Node's strip-types runner needs the source extension; the app tsconfig
// intentionally does not enable allowImportingTsExtensions.
const routingModulePath = "./mcpSkillRouting.ts";
const { getMcpSkillRoutingInfo } = await import(routingModulePath);

test("bundled Drivers identify all related skills, including shared capabilities", () => {
  const expected = {
    alarm: ["real-alarm", "alarm-analyst"],
    "cmdb-query": ["zgops-cmdb", "inspection-analyst", "alarm-analyst"],
    inspection: ["inspection-analyst", "alarm-analyst"],
    resource: ["resource-insight-query", "monitoring-overview-query"],
    order: ["order-workflow"],
    "web-check-app": ["web-availability-monitor"],
  };
  for (const [key, skills] of Object.entries(expected)) {
    assert.deepEqual(getMcpSkillRoutingInfo(key, true)?.skills, skills);
    assert.deepEqual(getMcpSkillRoutingInfo(key, false)?.skills, skills);
  }
});

test("enabled is a configuration state, and disabled script routing retains prerequisites", () => {
  assert.match(getMcpSkillRoutingInfo("alarm", true)!.description, /MCP 就绪后/);
  const disabled = getMcpSkillRoutingInfo("alarm", false)!.description;
  assert.match(disabled, /直接使用已有脚本，不先尝试 MCP/);
  assert.match(disabled, /依赖、凭据和授权/);
});

test("unknown or renamed Driver keys never promise a script fallback", () => {
  for (const key of ["custom-server", "Alarm", "告警服务", "", "toString", "__proto__"]) {
    assert.equal(getMcpSkillRoutingInfo(key, true), undefined);
    assert.equal(getMcpSkillRoutingInfo(key, false), undefined);
  }
});
