import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

test("SSO callback rejects URL credentials while preserving cookie bootstrap", async () => {
  const server = await createServer({
    root: fileURLToPath(new URL("../../", import.meta.url)),
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
      setTimeout,
      clearTimeout,
    },
  });
  let calls = 0;
  globalThis.fetch = async (_url, init) => {
    calls += 1;
    assert.equal(String(init?.body), "{}");
    return Response.json({
      access_token: "qp1.fixture",
      user: { userId: 7 },
      expires_in_seconds: 600,
    });
  };
  try {
    const { loginSsoCallback } = await server.ssrLoadModule("/src/api/sso.ts");
    for (const query of [
      "token=attacker",
      "code=unbound&state=guess",
      "token=",
      "code=",
    ]) {
      await assert.rejects(
        loginSsoCallback(new URLSearchParams(query)),
        /不接受 URL 登录凭据或授权码/,
      );
    }
    assert.equal(calls, 0);
    const result = await loginSsoCallback(new URLSearchParams());
    assert.equal(result.access_token, "qp1.fixture");
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow)
      Object.defineProperty(globalThis, "window", originalWindow);
    else Reflect.deleteProperty(globalThis, "window");
    await server.close();
  }
});
