import assert from "node:assert/strict";
import test from "node:test";
import {
  clearSession,
  getChatUserId,
  isAuthenticated,
  setSession,
  syncSsoTokenCookie,
} from "./ssoSession.ts";

test("chat identity follows the SSO username", () => {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const data = new Map<string, string>();
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key: string) => data.get(key) ?? null,
        setItem: (key: string, value: string) => data.set(key, value),
      },
    },
  });

  try {
    assert.equal(getChatUserId(), "default");
    setSession({
      token: "test-token",
      user: { userId: "123", username: " alice ", nickName: "Alice Smith" },
    });
    assert.equal(getChatUserId(), "alice");
    setSession({ token: "second-token", user: { username: "bob" } });
    assert.equal(getChatUserId(), "bob");
    setSession({ token: "missing-username", user: { userId: "123" } });
    assert.throws(() => getChatUserId(), /缺少用户名/);
    setSession({ token: "blank-username", user: { username: "  " } });
    assert.throws(() => getChatUserId(), /缺少用户名/);
  } finally {
    if (originalWindow) {
      Object.defineProperty(globalThis, "window", originalWindow);
    } else {
      Reflect.deleteProperty(globalThis, "window");
    }
  }
});

test("SSO cookie follows login, renewal, logout and expiry without extending the deadline", () => {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const originalDocument = Object.getOwnPropertyDescriptor(globalThis, "document");
  const data = new Map<string, string>();
  const document = { cookie: "" };
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      location: { protocol: "https:" },
      localStorage: {
        getItem: (key: string) => data.get(key) ?? null,
        setItem: (key: string, value: string) => data.set(key, value),
        removeItem: (key: string) => data.delete(key),
      },
    },
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: document,
  });
  try {
    setSession({ token: "test/token=value", expiresInSeconds: 60 });
    assert.match(document.cookie, /^qwenpaw_sso_token=test%2Ftoken%3Dvalue;/);
    assert.match(document.cookie, /Path=\/; SameSite=Strict; Secure; Max-Age=60$/);
    const deadline = data.get("qwenpaw.sso.expireAt");
    setSession({ token: "test/token=value", expiresInSeconds: 120 });
    assert.equal(data.get("qwenpaw.sso.expireAt"), deadline);
    assert.match(document.cookie, /Max-Age=60$/);

    clearSession();
    assert.match(document.cookie, /^qwenpaw_sso_token=;/);
    assert.match(document.cookie, /Max-Age=0$/);

    setSession({ token: "next-token", expiresInSeconds: 60 });
    data.set("qwenpaw.sso.expireAt", String(Date.now() - 1));
    syncSsoTokenCookie();
    assert.match(document.cookie, /Max-Age=0$/);
    assert.equal(isAuthenticated(), false);
    assert.equal(data.has("qwenpaw.sso.token"), false);
  } finally {
    if (originalWindow) {
      Object.defineProperty(globalThis, "window", originalWindow);
    } else {
      Reflect.deleteProperty(globalThis, "window");
    }
    if (originalDocument) {
      Object.defineProperty(globalThis, "document", originalDocument);
    } else {
      Reflect.deleteProperty(globalThis, "document");
    }
  }
});
