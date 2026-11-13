import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { bootstrapSso } from "./ssoBootstrap";
import { clearAuthToken, getApiToken, setAuthToken } from "./config";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

beforeEach(() => {
  localStorage.clear();
  setAuthToken("qp1.original");
  Object.defineProperty(window, "location", {
    configurable: true,
    value: {
      href: "https://portal.example/console/chat",
      assign: vi.fn(),
    },
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
});

it.each([
  ["session", "logout"],
  ["session", "replacement"],
  ["login", "logout"],
  ["login", "replacement"],
  ["session", "signed-out-url"],
  ["login", "signed-out-url"],
])("ignores late %s JSON after %s", async (stage, change) => {
  const reached = deferred<void>();
  const json = deferred<{ access_token: string }>();
  const delayed = {
    ok: true,
    status: 200,
    json: () => {
      reached.resolve();
      return json.promise;
    },
  };
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(Response.json({ sso_required: true }));
  if (stage === "session") fetcher.mockResolvedValueOnce(delayed);
  else
    fetcher
      .mockResolvedValueOnce(Response.json({}, { status: 401 }))
      .mockResolvedValueOnce(delayed);
  vi.stubGlobal("fetch", fetcher);
  const pending = bootstrapSso();
  await reached.promise;
  if (change === "signed-out-url") window.location.href += "?signed_out=1";
  else if (change === "logout") clearAuthToken();
  else setAuthToken("qp1.replacement");
  const expected = getApiToken();
  json.resolve({ access_token: "qp1.late-result" });
  expect(await pending).toBe(
    change !== "replacement" ? "signed-out" : "unavailable",
  );
  expect(getApiToken()).toBe(expected);
  expect(window.location.assign).not.toHaveBeenCalled();
});
