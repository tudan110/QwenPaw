import { beforeEach, describe, expect, it, vi } from "vitest";
import { bootstrapSso } from "./ssoBootstrap";
import { getApiToken, setAuthToken, clearAuthToken } from "./config";

vi.mock("./config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
  getApiToken: vi.fn(() => ""),
  setAuthToken: vi.fn(),
  clearAuthToken: vi.fn(),
}));

describe("SSO bootstrap before business components", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getApiToken).mockReturnValue("");
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        href: "https://portal.example/console/chat",
        protocol: "https:",
        hostname: "portal.example",
        assign: vi.fn(),
      },
    });
  });

  it("does not silently log in again after an explicit logout", async () => {
    window.location.href = "https://portal.example/console/chat?signed_out=1";
    global.fetch = vi.fn();
    expect(await bootstrapSso()).toBe("signed-out");
    expect(fetch).not.toHaveBeenCalled();
    expect(setAuthToken).not.toHaveBeenCalled();
  });

  it("restores an existing HttpOnly federation cookie without another login", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ sso_required: true }))
      .mockResolvedValueOnce(Response.json({ access_token: "qp1.cookie" }));
    expect(await bootstrapSso()).toBe("ready");
    expect(setAuthToken).toHaveBeenCalledWith("qp1.cookie");
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("obtains the first local token from the INOE cookie before plugins load", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ sso_required: true }))
      .mockResolvedValueOnce(Response.json({}, { status: 401 }))
      .mockResolvedValueOnce(Response.json({ access_token: "qp1.issued" }));
    expect(await bootstrapSso()).toBe("ready");
    expect(setAuthToken).toHaveBeenCalledWith("qp1.issued");
    expect(clearAuthToken).toHaveBeenCalledOnce();
  });

  it("expired sessions go to INOE with the original Console destination", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ sso_required: true }))
      .mockResolvedValueOnce(Response.json({}, { status: 401 }))
      .mockResolvedValueOnce(Response.json({}, { status: 401 }));
    expect(await bootstrapSso()).toBe("redirect");
    expect(window.location.assign).toHaveBeenCalledWith(
      "https://portal.example:30081/login?redirect=https%3A%2F%2Fportal.example%2Fconsole%2Fchat",
    );
  });

  it("validation outages never redirect to password login or render business UI", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ sso_required: true }))
      .mockResolvedValueOnce(Response.json({}, { status: 503 }));
    expect(await bootstrapSso()).toBe("unavailable");
    expect(window.location.assign).not.toHaveBeenCalled();
    expect(setAuthToken).not.toHaveBeenCalled();
  });

  it("an explicitly disabled SSO gate retains the legacy bootstrap path", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(Response.json({ sso_required: false }));
    expect(await bootstrapSso()).toBe("ready");
    expect(fetch).toHaveBeenCalledOnce();
  });
});
