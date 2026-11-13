import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createServer, type ViteDevServer } from "vite";

import type * as SsoConfig from "./ssoConfig";
import {
  clearSession,
  getSession,
  isSessionStorageKey,
  setSession,
} from "./ssoSession.ts";

let sso: typeof SsoConfig;
let server: ViteDevServer;

test.beforeEach(async () => {
  server = await createServer({
    root: fileURLToPath(new URL("../../", import.meta.url)),
    configFile: false,
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false },
    appType: "custom",
  });
  sso = await server.ssrLoadModule("/src/auth/ssoConfig.ts");
});

const originalWindow = globalThis.window;
const originalDocument = globalThis.document;
const originalFetch = globalThis.fetch;
const originalLocation = globalThis.location;

function createStorage() {
  const data = new Map<string, string>();
  return {
    getItem(key: string) {
      return data.has(key) ? data.get(key)! : null;
    },
    setItem(key: string, value: string) {
      data.set(key, String(value));
    },
    removeItem(key: string) {
      data.delete(key);
    },
    clear() {
      data.clear();
    },
  };
}

function setupBrowserEnv(options?: { pathname?: string; hidden?: boolean }) {
  const localStorage = createStorage();
  const listeners = new Map<string, Set<(event?: any) => void>>();
  const pathname = options?.pathname ?? "/";
  const hidden = options?.hidden ?? false;
  const locationState = {
    href: `http://portal.local:30083${pathname}`,
    origin: "http://portal.local:30083",
    protocol: "http:",
    hostname: "portal.local",
    pathname,
    search: "",
  };

  const document = {
    hidden,
    addEventListener(type: string, handler: (event?: any) => void) {
      if (!listeners.has(type)) {
        listeners.set(type, new Set());
      }
      listeners.get(type)!.add(handler);
    },
    removeEventListener(type: string, handler: (event?: any) => void) {
      listeners.get(type)?.delete(handler);
    },
    dispatch(type: string, event?: any) {
      for (const handler of listeners.get(type) ?? []) {
        handler(event);
      }
    },
  } as any;

  const windowObj = {
    localStorage,
    location: locationState,
    __PORTAL_RUNTIME_CONFIG__: {
      ssoEnabled: true,
      ssoInoePort: "30081",
      ssoLoginUrl: "http://portal.local:30081/login",
    },
    setInterval,
    clearInterval,
    setTimeout,
    clearTimeout,
    addEventListener(type: string, handler: (event?: any) => void) {
      if (!listeners.has(type)) {
        listeners.set(type, new Set());
      }
      listeners.get(type)!.add(handler);
    },
    removeEventListener(type: string, handler: (event?: any) => void) {
      listeners.get(type)?.delete(handler);
    },
    dispatch(type: string, event?: any) {
      for (const handler of listeners.get(type) ?? []) {
        handler(event);
      }
    },
  } as any;

  globalThis.window = windowObj;
  globalThis.document = document;
  globalThis.location = locationState as any;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ cleared: true }), {
      headers: { "Content-Type": "application/json" },
    });
  return { windowObj, document, locationState };
}

function restoreBrowserEnv() {
  globalThis.window = originalWindow;
  globalThis.document = originalDocument;
  globalThis.fetch = originalFetch;
  globalThis.location = originalLocation;
}

test.afterEach(async () => {
  clearSession();
  restoreBrowserEnv();
  await server.close();
});

test("isSessionStorageKey only matches portal SSO storage keys", () => {
  assert.equal(isSessionStorageKey("qwenpaw.sso.token"), true);
  assert.equal(isSessionStorageKey("qwenpaw.sso.user"), true);
  assert.equal(isSessionStorageKey("qwenpaw.sso.expireAt"), true);
  assert.equal(isSessionStorageKey("other"), false);
  assert.equal(isSessionStorageKey(null), false);
});

test("runtime config can enable SSO and drive the INOE origin", () => {
  const { windowObj } = setupBrowserEnv();
  windowObj.__PORTAL_RUNTIME_CONFIG__ = {
    ssoEnabled: true,
    ssoInoePort: "39081",
    ssoLoginUrl: "http://inoe.example.com:39081/login",
  };

  assert.equal(sso.isSsoEnabled(), true);
  assert.equal(sso.getInoeFrontendOrigin(), "http://inoe.example.com:39081");
  assert.equal(
    sso.getSsoLoginRedirectUrl("http://portal.local:30083/settings"),
    "http://inoe.example.com:39081/login?redirect=http%3A%2F%2Fportal.local%3A30083%2Fsettings",
  );
});

test("checkSsoSession clears the local session and redirects on 401", async () => {
  const { locationState } = setupBrowserEnv();
  setSession({
    token: "dead-token",
    user: { username: "zhiguan" },
    expiresInSeconds: 60,
  });

  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: "登录状态已过期" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });

  const ok = await sso.checkSsoSession(true);
  assert.equal(ok, false);
  assert.equal(getSession(), null);
  assert.equal(
    locationState.href,
    "http://portal.local:30081/login?redirect=http%3A%2F%2Fportal.local%3A30083%2F",
  );
});

test("triggerSsoRelogin only clears local state on allowlisted paths", async () => {
  const { locationState } = setupBrowserEnv({
    pathname: "/embed/knowledge-base",
  });
  setSession({
    token: "alive-token",
    user: { username: "zhiguan" },
    expiresInSeconds: 60,
  });

  await sso.triggerSsoRelogin();

  assert.equal(getSession(), null);
  assert.equal(
    locationState.href,
    "http://portal.local:30083/embed/knowledge-base",
  );
});

test("setupSsoSessionMonitor reacts to storage logout from another tab", async () => {
  const { windowObj } = setupBrowserEnv();
  setSession({
    token: "alive-token",
    user: { username: "zhiguan" },
    expiresInSeconds: 60,
  });

  const teardown = sso.setupSsoSessionMonitor();
  try {
    clearSession();
    windowObj.dispatch("storage", {
      storageArea: windowObj.localStorage,
      key: "qwenpaw.sso.token",
    });
    await new Promise((resolve) => setTimeout(resolve, 0));

    assert.equal(
      windowObj.location.href,
      "http://portal.local:30081/login?redirect=http%3A%2F%2Fportal.local%3A30083%2F",
    );
  } finally {
    teardown();
  }
});

test("renewal retains the local token namespace and server expiry", async () => {
  setupBrowserEnv();
  setSession({ token: "qp1.old", user: { userId: 7 }, expiresInSeconds: 60 });
  globalThis.fetch = async (_url, init) => {
    assert.equal(JSON.parse(String(init?.body)).token, "qp1.old");
    return new Response(
      JSON.stringify({
        access_token: "qp1.new",
        user: { userId: 7 },
        expires_in_seconds: 300,
      }),
      { headers: { "Content-Type": "application/json" } },
    );
  };
  const before = Date.now();
  assert.equal(await sso.checkSsoSession(true), true);
  assert.equal(getSession()?.token, "qp1.new");
  assert.ok(getSession()!.expireAt >= before + 300_000);
});

test("renewal outage does not logout or extend the existing expiry", async () => {
  const { locationState } = setupBrowserEnv();
  setSession({ token: "qp1.old", user: { userId: 7 }, expiresInSeconds: 60 });
  const expiry = getSession()!.expireAt;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({ detail: "authentication source unavailable" }),
      { status: 503, headers: { "Content-Type": "application/json" } },
    );
  assert.equal(await sso.checkSsoSession(true), true);
  assert.equal(getSession()?.token, "qp1.old");
  assert.equal(getSession()?.expireAt, expiry);
  assert.equal(locationState.href, "http://portal.local:30083/");
});

test(
  "unresponsive cookie cleanup is bounded and does not stall relogin",
  { timeout: 5_000 },
  async (context) => {
    const { locationState } = setupBrowserEnv();
    setSession({ token: "qp1.old", user: { userId: 7 }, expiresInSeconds: 60 });
    globalThis.fetch = async (_url, init) =>
      new Promise<Response>((_resolve, reject) => {
        const abort = () => reject(new DOMException("aborted", "AbortError"));
        if (init?.signal?.aborted) abort();
        else init?.signal?.addEventListener("abort", abort, { once: true });
      });
    context.mock.timers.enable({ apis: ["setTimeout"] });
    try {
      const relogin = sso.triggerSsoRelogin();
      context.mock.timers.tick(2_000);
      await relogin;
      assert.equal(getSession(), null);
      assert.match(locationState.href, /^http:\/\/portal.local:30081\/login\?/);
    } finally {
      context.mock.timers.reset();
    }
  },
);
