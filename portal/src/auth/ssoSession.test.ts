import assert from "node:assert/strict";
import test from "node:test";
import { getChatUserId, setSession } from "./ssoSession.ts";

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
