import { beforeEach, describe, expect, it, vi } from "vitest";
import { logoutConsole } from "./ssoLogout";
import { clearAuthToken } from "./config";

vi.mock("./config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
  getApiToken: () => "qp1.current",
  clearAuthToken: vi.fn(),
}));

describe("explicit Console logout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { href: "https://portal.example/console/chat", assign: vi.fn() },
    });
  });

  it("revokes the actual local credential before clearing it and navigating", async () => {
    global.fetch = vi.fn(async () => {
      expect(clearAuthToken).not.toHaveBeenCalled();
      return Response.json({ logged_out: true });
    });
    await logoutConsole(true);
    expect(fetch).toHaveBeenCalledWith(
      "/api/portal/sso/logout",
      expect.objectContaining({
        method: "POST",
        headers: { Authorization: "Bearer qp1.current" },
      }),
    );
    expect(clearAuthToken).toHaveBeenCalledOnce();
    expect(window.location.assign).toHaveBeenCalledWith(
      "https://portal.example/console/chat?signed_out=1",
    );
  });

  it("cleans expired cookie sessions before reporting success", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(Response.json({}, { status: 401 }))
      .mockResolvedValueOnce(Response.json({ cleared: true }));
    await logoutConsole(true);
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/portal/sso/clear-login-cookie",
      expect.objectContaining({ method: "POST" }),
    );
    expect(clearAuthToken).toHaveBeenCalledOnce();
  });

  it.each([403, 503])(
    "does not claim revocation after HTTP %s",
    async (status) => {
      global.fetch = vi.fn().mockResolvedValue(Response.json({}, { status }));
      await expect(logoutConsole(true)).rejects.toThrow("退出未完成");
      expect(clearAuthToken).not.toHaveBeenCalled();
      expect(window.location.assign).not.toHaveBeenCalled();
    },
  );

  it("retains credentials when cookie cleanup also fails", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(Response.json({}, { status: 401 }))
      .mockResolvedValueOnce(Response.json({}, { status: 503 }));
    await expect(logoutConsole(true)).rejects.toThrow();
    expect(clearAuthToken).not.toHaveBeenCalled();
  });

  it("rejects an unconfirmed 200 response from a proxy", async () => {
    global.fetch = vi.fn().mockResolvedValue(Response.json({}));
    await expect(logoutConsole(true)).rejects.toThrow("退出未完成");
    expect(clearAuthToken).not.toHaveBeenCalled();
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("keeps the explicitly disabled native logout path usable", async () => {
    global.fetch = vi.fn();
    await logoutConsole(false);
    expect(fetch).not.toHaveBeenCalled();
    expect(clearAuthToken).toHaveBeenCalledOnce();
  });
});
