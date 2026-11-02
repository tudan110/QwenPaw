import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { toFriendlyChatError } from "../lib/chatErrorMessage.ts";

test("reconnect preserves the selected chat identity instead of the SSO viewer", async () => {
  const server = await createServer({
    root: fileURLToPath(new URL("../..", import.meta.url)),
    configFile: false,
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false },
    appType: "custom",
  });
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const originalFetch = globalThis.fetch;
  const storage = new Map<string, string>();
  const requests: Array<Record<string, unknown>> = [];
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => storage.set(key, value),
      },
      setTimeout,
      clearTimeout,
    },
  });
  globalThis.fetch = async (_input, init) => {
    requests.push(JSON.parse(String(init?.body)));
    return new Response("", { status: 200 });
  };

  try {
    const { setSession } = await server.ssrLoadModule("/src/auth/ssoSession.ts");
    const { reconnectChat } = await server.ssrLoadModule("/src/api/copawChat.ts");
    for (const username of ["alice", "bob"]) {
      setSession({ token: `test-${username}`, user: { username } });
      await reconnectChat("fault", {
        sessionId: "portal-fault-alarm-test",
        userId: "default",
        channel: "console",
      });
      assert.deepEqual(requests[requests.length - 1], {
        reconnect: true,
        session_id: "portal-fault-alarm-test",
        user_id: "default",
        channel: "console",
        stream: true,
      });
      await reconnectChat("fault", { sessionId: "personal-chat" });
      assert.equal(requests[requests.length - 1]?.user_id, username);
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

test("HTTP 200 failed SSE preserves the safe Kunlun category for user-facing advice", async () => {
  const server = await createServer({
    root: fileURLToPath(new URL("../..", import.meta.url)),
    configFile: false,
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false },
    appType: "custom",
  });
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const originalFetch = globalThis.fetch;
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { setTimeout, clearTimeout },
  });

  try {
    const { streamChat } = await server.ssrLoadModule("/src/api/copawChat.ts");
    const cases = [
      ["KUNLUN_MODEL_UNAUTHORIZED", /模型未授权/],
      ["KUNLUN_ROUTE_NOT_FOUND", /接口未找到/],
      ["KUNLUN_SERVICE_UNAVAILABLE", /网关或模型服务暂时不可用/],
    ] as const;
    for (const [code, expected] of cases) {
      globalThis.fetch = async () => {
        const event = {
          object: "response",
          status: "failed",
          output: [],
          error: `Kunlun model request failed (${code})`,
        };
        const bytes = new TextEncoder().encode(
          `data: ${JSON.stringify(event)}\n\n`,
        );
        return new Response(
          new ReadableStream({
            start(controller) {
              controller.enqueue(bytes.slice(0, 27));
              controller.enqueue(bytes.slice(27));
              controller.close();
            },
          }),
          { status: 200, headers: { "Content-Type": "text/event-stream" } },
        );
      };

      await assert.rejects(
        streamChat("gateway", {
          session_id: "kunlun-error-test",
          stream: true,
        }),
        (error: unknown) => {
          assert.ok(error instanceof Error);
          assert.match(error.message, new RegExp(code));
          assert.match(toFriendlyChatError(error), expected);
          assert.doesNotMatch(toFriendlyChatError(error), /KUNLUN_/);
          return true;
        },
      );
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
