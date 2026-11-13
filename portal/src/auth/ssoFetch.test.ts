import assert from "node:assert/strict";
import test from "node:test";
import { createSsoFetch } from "./ssoFetch.ts";

test("local federation credentials are not sent as INOE business JWTs", async () => {
  const fetchApi = createSsoFetch(
    async (_input, init) => {
      const headers = new Headers(init?.headers);
      assert.equal(headers.get("X-QwenPaw-Access-Token"), "qp1.fixture");
      assert.equal(headers.has("X-Inoe-Token"), false);
      return new Response("data: ready\n\n");
    },
    "https://portal.example/",
    ["/copaw-api"],
    () => "qp1.fixture",
    () => assert.fail("unexpected relogin"),
  );
  const response = await fetchApi("/copaw-api/api/console/chat", {
    method: "POST", headers: { "X-Inoe-Token": "stale" },
  });
  assert.equal(await response.text(), "data: ready\n\n");
});

test("SSO headers cover core, portal, configured APIs and streaming without changing payloads", async () => {
  const calls: { input: RequestInfo | URL; init?: RequestInit }[] = [];
  const response = new Response("data: ready\n\n");
  let token = "first-token";
  const fetchApi = createSsoFetch(
    async (input, init) => { calls.push({ input, init }); return response; },
    "https://portal.example/home",
    ["/api", "/api/portal", "/portal-api", "/copaw-api/api", "https://backend.example/api"],
    () => token,
    () => assert.fail("unexpected 401"),
  );
  const controller = new AbortController();
  for (const path of [
    "/api/chats",
    "/portal-api/employee-status",
    "/copaw-api/api/console/chat",
    "https://backend.example/api/agents/gateway/chats",
  ]) {
    const body = new FormData();
    body.append("file", "test");
    const result = await fetchApi(path, {
      method: "POST",
      headers: { "X-Agent-Id": "gateway" },
      body,
      signal: controller.signal,
    });
    assert.equal(result, response);
    const init = calls.at(-1)!.init!;
    const headers = new Headers(init.headers);
    assert.equal(headers.get("X-Inoe-Token"), token);
    assert.equal(headers.get("X-Agent-Id"), "gateway");
    assert.equal(headers.has("Content-Type"), false);
    assert.equal(init.body, body);
    assert.equal(init.signal, controller.signal);
    token = "next-token";
  }
});

test("Request headers survive, current session token replaces stale token", async () => {
  const fetchApi = createSsoFetch(
    async (_input, init) => {
      const headers = new Headers(init?.headers);
      assert.equal(headers.get("X-Agent-Id"), "gateway");
      assert.equal(headers.get("X-Inoe-Token"), "fresh-token");
      return new Response();
    },
    "https://portal.example/",
    ["/api"],
    () => "fresh-token",
    () => {},
  );
  await fetchApi(new Request("https://portal.example/api/chats", {
    headers: new Headers({ "X-Agent-Id": "gateway", "X-Inoe-Token": "old-token" }),
  }));
});

test("SSO token is not sent to static files, lookalike paths or third-party origins", async () => {
  const fetchApi = createSsoFetch(
    async (_input, init) => {
      assert.equal(init, undefined);
      return new Response();
    },
    "https://portal.example/",
    ["/api", "/portal-api"],
    () => assert.fail("unrelated URL must not read token"),
    () => {},
  );
  for (const url of ["/assets/app.js", "/api-other", "https://other.example/api/chats"]) {
    await fetchApi(url);
  }
});

test("401 handling excludes only login endpoints and covers same-origin fallback", async () => {
  let unauthorized = 0;
  const fetchApi = createSsoFetch(
    async () => new Response(null, { status: 401 }),
    "https://portal.example/",
    ["/api", "/api/portal", "/portal-api", "/copaw-api/api"],
    () => undefined,
    () => { unauthorized++; },
  );
  for (const prefix of ["/portal-api", "/api/portal"]) {
    await fetchApi(`${prefix}/sso/status`);
    await fetchApi(`${prefix}/sso/token-login`, { method: "POST" });
    await fetchApi(`${prefix}/sso/exchange`, { method: "POST" });
    await fetchApi(`${prefix}/sso/clear-login-cookie`, { method: "POST" });
  }
  assert.equal(unauthorized, 0);
  await fetchApi("/copaw-api/api/chats");
  await fetchApi("/api/portal/sso/sso-settings");
  assert.equal(unauthorized, 2);
});
