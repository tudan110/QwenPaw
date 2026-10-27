import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

test("approval UI renders scoped choices, expiry, errors and inherited defaults", async () => {
  const server = await createServer({
    root: fileURLToPath(new URL("../../..", import.meta.url)),
    configFile: false,
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false },
    appType: "custom",
  });
  try {
    const { MainChatApprovalPanel, MainChatApprovalModeSelector } = await server.ssrLoadModule(
      "/src/pages/digital-employee/mainChatApprovalControls.tsx",
    );
    const approval = {
      request_id: "request-1",
      session_id: "child",
      root_session_id: "root",
      agent_id: "worker",
      owner_agent_id: "agent-a",
      tool_name: "Write",
      tool_source: "STRICT mode",
      severity: "HIGH",
      findings_count: 1,
      result_summary: "<script>untrusted tool content</script>",
      exact_target: "/tmp/test.txt",
      similar_target: "/tmp/**",
      is_generalized: true,
      created_at: Date.now() / 1000,
      timeout_seconds: 300,
    };
    const controls = {
      items: [approval], busy: {}, error: "", notice: "", act: async () => {}, retry: () => {},
    };
    const render = () => renderToStaticMarkup(createElement(MainChatApprovalPanel, { controls }));
    const html = render();
    for (const text of ["批准精确目标", "批准通用规则", "拒绝", "取消任务", "子智能体：", "/tmp/**", "严格模式", "高风险"]) {
      assert.ok(html.includes(text), text);
    }
    assert.ok(html.includes("&lt;script&gt;"));
    assert.ok(!html.includes("<script>"));
    approval.created_at -= 400;
    const expired = render();
    assert.match(expired, /审批已超时/);
    assert.equal((expired.match(/disabled=""/g) || []).length, 3);
    controls.items = [];
    assert.equal(render(), "");
    controls.error = "审批接口不可用";
    assert.match(render(), /role="alert"/);
    assert.match(render(), /刷新状态/);
    controls.error = "";
    controls.notice = "该审批已失效。本次操作未获确认，请重新发起任务。";
    assert.match(render(), /role="status"/);
    assert.match(render(), /该审批已失效/);
    assert.ok(!render().includes("批准精确目标"));
    const selector = renderToStaticMarkup(createElement(MainChatApprovalModeSelector, {
      level: null, onChange: () => {}, disabled: false, error: "",
    }));
    assert.match(selector, /工具执行安全：默认模式/);
  } finally {
    await server.close();
  }
});
