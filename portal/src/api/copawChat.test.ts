import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

test("reconnect preserves the selected chat identity instead of the SSO viewer", async () => {
  const server = await createServer({
    root: fileURLToPath(new URL("../..", import.meta.url)),
    configFile: false,
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true },
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
