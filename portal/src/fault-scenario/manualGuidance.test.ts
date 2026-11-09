import assert from "node:assert/strict";
import test from "node:test";

import {
  MANUAL_FAULT_GUIDANCE_INSTRUCTIONS,
  isManualFaultAdviceOnly,
  withManualFaultGuidance,
} from "./manualGuidance.ts";
import { getManualOperationGuide, type ManualOperationGuide } from "./shared.ts";

test("fault advice retains current deployment and manual-only requirements", () => {
  const text = withManualFaultGuidance("分析 MySQL 慢 SQL 并给处置建议");
  assert.ok(text.includes("K3s/Kubernetes、裸 Docker、主机"));
  assert.ok(text.includes("组件访问"));
  assert.ok(text.includes("多行 shell/SQL"));
  assert.ok(text.includes("不索要/获取"));
  assert.ok(text.includes("不生成自动执行 action"));
  assert.ok(text.includes("Step 0"));
  assert.ok(text.includes("禁止 AI 执行 SSH 不等于禁止"));
  assert.ok(text.includes("不能直接用作容器内"));
});

test("ordinary chat is unchanged and fault policy is not duplicated", () => {
  assert.equal(withManualFaultGuidance("你好"), "你好");
  assert.equal(
    withManualFaultGuidance(MANUAL_FAULT_GUIDANCE_INSTRUCTIONS),
    MANUAL_FAULT_GUIDANCE_INSTRUCTIONS,
  );
});

test("slow SQL advice without an alarm does not enter automatic workorder flow", () => {
  assert.equal(isManualFaultAdviceOnly("mysql-01 慢 SQL 如何处置"), true);
  assert.equal(isManualFaultAdviceOnly("慢 SQL 告警如何处置"), false);
  assert.equal(isManualFaultAdviceOnly("慢 SQL 如何处置", { alarmId: "a" }), false);
});

test("alarm-bound chats apply the same policy for any configured agent", () => {
  assert.ok(
    withManualFaultGuidance("CPU 利用率超限", { alarmId: "alarm-1" })
      .includes(MANUAL_FAULT_GUIDANCE_INSTRUCTIONS),
  );
});

test("manual guide protocol preserves complete command text without an action", () => {
  const guide: ManualOperationGuide = {
    source: "cmdb-only",
    executionMode: "manual-only",
    deploymentKind: "kubernetes",
    deploymentConfirmed: false,
    relatedPlatforms: [],
    knownParameters: {},
    missingParameters: ["NAMESPACE"],
    markdown: "1. 人工执行\n```bash\nkubectl get pods\n```\n```sql\nSHOW FULL PROCESSLIST;\n```",
  };
  assert.equal(getManualOperationGuide(guide), guide);
  assert.equal(getManualOperationGuide(), null);
  const invalid = JSON.parse(JSON.stringify(guide));
  invalid.executionMode = "auto";
  assert.throws(() => getManualOperationGuide(invalid), /协议无效/);
});
