import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

test("reopening failed chats restores messages without replacing the error with an old reply", async () => {
  const server = await createServer({
    root: fileURLToPath(new URL("../../..", import.meta.url)),
    configFile: false,
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false },
    appType: "custom",
  });
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const originalFetch = globalThis.fetch;
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: { getItem: () => null },
      setTimeout, clearTimeout, clearInterval,
    },
  });
  const user = { id: "user", role: "user", type: "message", content: [{ type: "text", text: "你好" }] };
  const failure = {
    id: "error", role: "assistant", type: "message",
    content: [{ type: "text", text: "本轮对话失败。" }],
    metadata: { metadata: { portal_chat_error: "MODEL_API_KEY_MISSING" } },
  };
  try {
    const { useRemoteChatSession } = await server.ssrLoadModule(
      "/src/pages/digital-employee/useRemoteChatSession.ts",
    );
    for (const mode of ["persisted", "trace-only", "user-already-saved", "previous-answer"]) {
      let messages: any[] = [];
      let recoveryRequests = 0;
      const previousAnswer = {
        id: "old-answer", role: "assistant", type: "message",
        content: [{ type: "text", text: "之前的回答" }],
      };
      globalThis.fetch = async (input) => {
        const url = String(input);
        if (url.includes("trace-recovery")) {
          recoveryRequests += 1;
          return Response.json({
            available: true, is_error: true,
            user_message: user, message: failure,
          });
        }
        assert.match(url, /\/chats\/failed-chat$/);
        return Response.json({
          messages: mode === "persisted" ? [user, failure]
            : mode === "user-already-saved" ? [user]
              : mode === "previous-answer" ? [user, previousAnswer] : [],
          status: "idle",
        });
      };
      let selectHistory: (session: unknown) => Promise<void>;
      function Harness() {
        const remote = useRemoteChatSession({
          currentEmployee: { id: "test-employee", name: "测试助手" },
          isRemoteEmployee: true,
          remoteAgentId: "gateway",
          setMessages: (value: any) => {
            messages = typeof value === "function" ? value(messages) : value;
          },
        });
        selectHistory = remote.handleSelectRemoteHistory;
        return null;
      }
      renderToStaticMarkup(createElement(Harness));
      await selectHistory!({
        id: "failed-chat", sessionId: "failed-session",
        userId: "alice", channel: "console",
      });
      assert.equal(messages.length, mode === "previous-answer" ? 4 : 2, mode);
      assert.equal(messages.at(-2).content, "你好", mode);
      assert.equal(messages.at(-1).chatError, true, mode);
      assert.match(messages.at(-1).content, /对话失败：.*未收到 API Key/, mode);
      assert.equal(recoveryRequests, mode === "persisted" ? 0 : 1, mode);
      if (mode === "previous-answer") {
        assert.equal(messages[1].processBlocks[0].content, "之前的回答");
      }
    }
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow) {
      Object.defineProperty(globalThis, "window", originalWindow);
    } else {
      Reflect.deleteProperty(globalThis, "window");
    }
    await server.close();
  }
});
