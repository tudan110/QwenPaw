import assert from "node:assert/strict";
import test from "node:test";

import { workspaceDisplayName } from "./workspaceDisplay.ts";

test("uses the configured Chinese digital-employee name for known workspaces", () => {
  assert.equal(workspaceDisplayName("fault"), "故障分析专家");
  assert.equal(workspaceDisplayName("knowledge"), "知识库助手");
  assert.equal(workspaceDisplayName("query"), "数据分析专家");
});

test("keeps an unknown workspace identifier visible", () => {
  assert.equal(workspaceDisplayName("custom-ops"), "custom-ops");
});


test("uses the product name and an optional public fallback", () => {
  assert.equal(workspaceDisplayName("gateway", "数字员工"), "智观AI");
  assert.equal(workspaceDisplayName("custom-ops", "数字员工"), "数字员工");
});
