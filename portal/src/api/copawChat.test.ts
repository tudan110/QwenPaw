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

test("HTTP 200 failed SSE preserves safe model categories for user-facing advice", async () => {
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
      ["MODEL_API_KEY_MISSING", /未收到 API Key/],
      ["MODEL_API_KEY_INVALID", /API Key 校验失败/],
      ["MODEL_AUTH_FAILED", /身份验证失败/],
      ["MODEL_ACCESS_DENIED", /无权访问所选模型/],
    ] as const;
    for (const [code, expected] of cases) {
      globalThis.fetch = async () => {
        const event = {
          object: "response",
          status: "failed",
          output: [],
          error: `Model request failed (${code})`,
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
          assert.doesNotMatch(toFriendlyChatError(error), /KUNLUN_|MODEL_/);
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


test("Portal streaming distinguishes a known input denial from unrelated HTTP failures", async () => {
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
    const { toFriendlyChatError: displayError } = await server.ssrLoadModule("/src/lib/chatErrorMessage.ts");
    const denial = "安全策略拦截了疑似越权指令，请改用正常业务描述。（规则：identity-spoof）";
    const fallback = "服务暂时遇到点问题，请稍后重试。";
    const cases = [
      [403, denial, "安全策略已拦截本次请求（疑似冒用管理员或系统身份），请改用正常业务描述。"],
      [403, "当前账号没有权限。", fallback],
      [403, `${denial} /tmp/internal-detail`, fallback],
      [500, denial, fallback],
    ] as const;
    for (const [status, detail, expected] of cases) {
      globalThis.fetch = async () => Response.json({ detail }, { status });
      await assert.rejects(streamChat("gateway", { stream: true }), (error: unknown) => {
        assert.equal(displayError(error), expected);
        return true;
      });
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

test("disabled business tools never fall back to normal chat when the backend lacks the route", async () => {
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
    value: { setTimeout, clearTimeout, localStorage: { getItem: () => null } },
  });
  const paths: string[] = [];
  globalThis.fetch = async (input) => {
    paths.push(String(input));
    return Response.json({ detail: "Not Found" }, { status: 404 });
  };
  try {
    const { streamChat } = await server.ssrLoadModule("/src/api/copawChat.ts");
    await assert.rejects(
      streamChat("gateway", { stream: true }, { modelOnly: true }),
      /Not Found/,
    );
    assert.equal(paths.length, 1);
    assert.match(paths[0], /\/console\/chat\/model-only$/);
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
