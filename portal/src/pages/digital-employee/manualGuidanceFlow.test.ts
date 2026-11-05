import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

test("fault policy stays scoped to the actual chat and does not alter scenario routing", async () => {
  const server = await createServer({
    root: fileURLToPath(new URL("../../..", import.meta.url)),
    configFile: false,
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false },
    appType: "custom",
  });
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const originalFetch = globalThis.fetch;
  const storage = new Map<string, string>();
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => storage.set(key, value),
        removeItem: (key: string) => storage.delete(key),
      },
      setTimeout, clearTimeout, setInterval, clearInterval,
      dispatchEvent: () => true,
    },
  });
  const streamedInputs: string[] = [];
  const unexpectedRequests: string[] = [];
  let createdChats = 0;
  let scenarioCalls = 0;
  globalThis.fetch = async (input, options) => {
    const path = String(input);
    if (path.endsWith("/console/chat")) {
      const body = JSON.parse(String(options?.body));
      streamedInputs.push(body.input[0].content[0].text);
      return new Response("", { headers: { "Content-Type": "text/event-stream" } });
    }
    if (path.endsWith("/chats") && options?.method === "POST") {
      createdChats += 1;
      const body = JSON.parse(String(options.body));
      return Response.json({ id: `chat-${createdChats}`, ...body });
    }
    if (path.includes("/alarm-analyst/diagnose")) {
      scenarioCalls += 1;
      return Response.json({ result: { summary: "已取得原场景结果" } });
    }
    if (!/\/chats(?:\?|$)/.test(path)) unexpectedRequests.push(path);
    return Response.json([]);
  };
  try {
    const { useRemoteChatSession } = await server.ssrLoadModule(
      "/src/pages/digital-employee/useRemoteChatSession.ts",
    );
    for (const agent of ["query", "fault"]) {
      let remote: ReturnType<typeof useRemoteChatSession>;
      let messages: any[] = [];
      function Harness() {
        remote = useRemoteChatSession({
          currentEmployee: { id: agent, name: "测试助手" },
          isRemoteEmployee: true,
          remoteAgentId: agent,
          setMessages: (value: any) => {
            messages = typeof value === "function" ? value(messages) : value;
          },
        });
        return null;
      }
      renderToStaticMarkup(createElement(Harness));
      assert.equal(await remote!.handleRemoteSendMessage("你好"), true, JSON.stringify(messages));
      assert.equal(streamedInputs[streamedInputs.length - 1], "你好");
      assert.equal(await remote!.handleRemoteSendMessage("分析 MySQL 慢 SQL"), true);
      assert.ok(streamedInputs[streamedInputs.length - 1]?.includes("[CMDB 人工处置指南约束]"));
      assert.equal(scenarioCalls, 0);
      assert.equal(
        await remote!.handleRemoteSendMessage("核对现象", {
          forceNewChat: true, chatMeta: { alarmId: "fixture-alarm" },
        }),
        true,
      );
      assert.ok(streamedInputs[streamedInputs.length - 1]?.includes("[CMDB 人工处置指南约束]"));
      assert.equal(
        await remote!.handleRemoteSendMessage("你好", { forceNewChat: true }),
        true,
      );
      assert.equal(streamedInputs[streamedInputs.length - 1], "你好");
      if (agent === "fault") {
        assert.equal(
          await remote!.handleRemoteSendMessage("cmdb 应用插入失败", {
            sessionId: "fixture-session",
          }),
          true,
        );
        assert.equal(scenarioCalls, 1);
      }
    }
    assert.deepEqual(unexpectedRequests, []);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow) Object.defineProperty(globalThis, "window", originalWindow);
    else Reflect.deleteProperty(globalThis, "window");
    await server.close();
  }
});
