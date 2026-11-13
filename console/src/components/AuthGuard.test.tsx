import { act, cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AuthGuard from "./AuthGuard";
import { clearAuthToken, getApiToken, setAuthToken } from "../api/config";

vi.mock("../api/modules/auth", () => ({
  authApi: { getStatus: vi.fn(async () => ({ enabled: false })) },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

async function mountGuard() {
  let view!: ReturnType<typeof render>;
  await act(async () => {
    view = render(
      <MemoryRouter>
        <AuthGuard>
          <div>private-content</div>
        </AuthGuard>
      </MemoryRouter>,
    );
  });
  return view;
}

describe("Console authentication async state ownership", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    setAuthToken("qp1.start");
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it.each(["logout", "new-login", "unmount", "same-token-new-login"])(
    "does not apply a renewal JSON response after %s",
    async (mode) => {
      const json = deferred<{ access_token: string }>();
      const readJson = vi.fn(() => json.promise);
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValueOnce(Response.json({ sso_required: true }))
          .mockResolvedValueOnce(Response.json({ access_token: "qp1.ready" }))
          .mockResolvedValueOnce({ ok: true, status: 200, json: readJson }),
      );
      const view = await mountGuard();
      expect(screen.getByText("private-content")).toBeInTheDocument();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });
      expect(readJson).toHaveBeenCalledOnce();
      if (mode === "unmount") view.unmount();
      else if (mode === "logout") clearAuthToken();
      else if (mode === "new-login") setAuthToken("qp1.other-user");
      else {
        clearAuthToken();
        setAuthToken("qp1.ready");
      }
      const expected = getApiToken();
      await act(async () => {
        json.resolve({ access_token: "qp1.late-renewal" });
      });
      expect(getApiToken()).toBe(expected);
    },
  );

  it("applies a valid renewal while the requesting login is current", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(Response.json({ sso_required: true }))
        .mockResolvedValueOnce(Response.json({ access_token: "qp1.ready" }))
        .mockResolvedValueOnce(Response.json({ access_token: "qp1.renewed" })),
    );
    await mountGuard();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(getApiToken()).toBe("qp1.renewed");
  });

  it("can clear a stale local token and then accept its own cookie fallback", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(Response.json({ sso_required: true }))
        .mockResolvedValueOnce(Response.json({}, { status: 401 }))
        .mockResolvedValueOnce(
          Response.json({ access_token: "qp1.from-cookie" }),
        ),
    );
    await mountGuard();
    expect(getApiToken()).toBe("qp1.from-cookie");
    expect(screen.getByText("private-content")).toBeInTheDocument();
  });

  it("preserves the explicitly disabled native authentication workflow", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(Response.json({ sso_required: false })),
    );
    await mountGuard();
    expect(screen.getByText("private-content")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledOnce();
  });

  it.each(["logout", "new-login", "unmount"])(
    "does not apply initial-login JSON after %s",
    async (mode) => {
      const json = deferred<{ access_token: string }>();
      const readJson = vi.fn(() => json.promise);
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValueOnce(Response.json({ sso_required: true }))
          .mockResolvedValueOnce({ ok: true, status: 200, json: readJson }),
      );
      const view = await mountGuard();
      expect(readJson).toHaveBeenCalledOnce();
      if (mode === "unmount") view.unmount();
      else if (mode === "logout") clearAuthToken();
      else setAuthToken("qp1.other-user");
      const expected = getApiToken();
      await act(async () => {
        json.resolve({ access_token: "qp1.late-bootstrap" });
      });
      expect(getApiToken()).toBe(expected);
    },
  );

  it("does not clear another login when an older renewal returns 401", async () => {
    const response = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(Response.json({ sso_required: true }))
        .mockResolvedValueOnce(Response.json({ access_token: "qp1.ready" }))
        .mockReturnValueOnce(response.promise),
    );
    await mountGuard();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    setAuthToken("qp1.other-user");
    await act(async () => {
      response.resolve(Response.json({}, { status: 401 }));
    });
    expect(getApiToken()).toBe("qp1.other-user");
  });
});
