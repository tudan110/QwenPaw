import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

test("main-chat approval API scopes requests and preserves approval semantics", async () => {
  const server = await createServer({
    root: fileURLToPath(new URL("../..", import.meta.url)),
    configFile: false,
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false },
    appType: "custom",
  });
  const originalFetch = globalThis.fetch;
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const lastRequest = () => requests[requests.length - 1];
  let result: unknown = { pending_approvals: [] };
  let status = 200;
  globalThis.fetch = async (url, init) => {
    requests.push({ url: String(url), init });
    return new Response(JSON.stringify(result), { status });
  };
  try {
    const api = await server.ssrLoadModule("/src/api/mainChatApproval.ts");
    const signal = new AbortController().signal;
    await api.listMainChatApprovals("agent-a", "root/a &b", signal);
    const listed = lastRequest();
    assert.equal(listed?.url, "/copaw-api/api/approval/list?session_id=root%2Fa%20%26b");
    assert.deepEqual(listed?.init?.headers, { "X-Agent-Id": "agent-a" });
    assert.equal(listed?.init?.signal, signal);
    assert.equal(listed?.init?.method, "GET");
    assert.equal(listed?.init?.cache, "no-store");
    await assert.rejects(api.listMainChatApprovals("agent-a", "", signal), /缺少/);

    result = { success: true };
    await api.resolveMainChatApproval("agent-a", "root", "child-request", "approve", signal);
    assert.deepEqual(JSON.parse(String(lastRequest()?.init?.body)), {
      request_id: "child-request", session_id: "root", scope: "exact",
    });
    await api.resolveMainChatApproval("agent-a", "root", "child-request", "approve", signal, "similar");
    assert.equal(JSON.parse(String(lastRequest()?.init?.body)).scope, "similar");
    await api.resolveMainChatApproval("agent-a", "root", "child-request", "deny", signal, "similar");
    assert.deepEqual(JSON.parse(String(lastRequest()?.init?.body)), {
      request_id: "child-request", session_id: "root",
    });

    result = { success: false, message: "already resolved" };
    await assert.rejects(
      api.resolveMainChatApproval("agent-a", "root", "request", "approve", signal),
      /already resolved/,
    );
    status = 403;
    result = { detail: "Root session mismatch" };
    await assert.rejects(api.listMainChatApprovals("agent-a", "root", signal), /Root session mismatch/);
    assert.equal(api.isMissingApprovalRequest(new Error("Approval request not found: plain")), false);
    for (const [code, detail, expected] of [
      [404, "Approval request not found: fb12f25a-4dd2-49", true],
      [404, "Not Found", false],
      [403, "Approval request not found: forbidden", false],
      [500, "Internal Server Error", false],
    ] as const) {
      status = code;
      result = { detail };
      await assert.rejects(
        api.resolveMainChatApproval("agent-a", "root", "request", "approve", signal),
        (error: unknown) => {
          assert.ok(error instanceof api.MainChatApprovalApiError);
          assert.equal((error as { status: number }).status, code);
          assert.equal(api.isMissingApprovalRequest(error), expected);
          return true;
        },
      );
    }
    status = 200;
    result = {};
    await assert.rejects(api.listMainChatApprovals("agent-a", "root", signal), /格式异常/);

    result = { stopped: false };
    await assert.rejects(api.stopMainChatApprovalTask("agent-a", "chat/1", signal), /任务未停止/);
    result = { stopped: true };
    await api.stopMainChatApprovalTask("agent-a", "chat/1", signal);
    assert.equal(lastRequest()?.url, "/copaw-api/api/console/chat/stop?chat_id=chat%2F1");
    assert.equal(lastRequest()?.init?.method, "POST");
  } finally {
    globalThis.fetch = originalFetch;
    await server.close();
  }
});
