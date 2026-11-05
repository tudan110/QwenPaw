import assert from "node:assert/strict";
import test from "node:test";

import {
  MANUAL_FAULT_GUIDANCE_INSTRUCTIONS,
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
});

test("ordinary chat is unchanged and fault policy is not duplicated", () => {
  assert.equal(withManualFaultGuidance("你好"), "你好");
  assert.equal(
    withManualFaultGuidance(MANUAL_FAULT_GUIDANCE_INSTRUCTIONS),
    MANUAL_FAULT_GUIDANCE_INSTRUCTIONS,
  );
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
