import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatApi } from "../../api/modules/chat";
import { useStopFeedback } from "./useStopFeedback";

vi.mock("../../api/modules/chat", () => ({ chatApi: { stopChat: vi.fn() } }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("stop feedback reflects the request, not remote termination", () => {
  beforeEach(() => vi.clearAllMocks());
  it.each([
    [true, "accepted"],
    [false, "notRunning"],
  ])("uses the server flag %s", async (stopped, status) => {
    vi.mocked(chatApi.stopChat).mockResolvedValue({
      stopped: stopped as boolean,
    });
    const { result } = renderHook(() => useStopFeedback("session-a"));
    await act(async () => {
      await result.current.requestStop("chat-a");
    });
    expect(result.current.notice?.props.message).toContain(
      `trustedEvidence.stop.${status}`,
    );
    expect(result.current.notice?.props.description).toBe(
      "trustedEvidence.stopBoundary",
    );
    expect(chatApi.stopChat).toHaveBeenCalledWith("chat-a");
  });
  it("keeps failure distinct and preserves error propagation", async () => {
    vi.mocked(chatApi.stopChat).mockRejectedValue(new Error("offline"));
    const { result } = renderHook(() => useStopFeedback("session-a"));
    await act(async () => {
      await expect(result.current.requestStop("chat-a")).rejects.toThrow(
        "offline",
      );
    });
    expect(result.current.notice?.props.message).toContain(
      "trustedEvidence.stop.failed",
    );
  });
  it("hides notices when the user switches sessions", async () => {
    vi.mocked(chatApi.stopChat).mockResolvedValue({ stopped: true });
    const { result, rerender } = renderHook(
      ({ scope }) => useStopFeedback(scope),
      { initialProps: { scope: "session-a" } },
    );
    await act(async () => {
      await result.current.requestStop("chat-a");
    });
    rerender({ scope: "session-b" });
    expect(result.current.notice).toBeNull();
  });
  it("ignores a late response from an older stop request", async () => {
    let resolveOlder!: (value: { stopped: boolean }) => void;
    vi.mocked(chatApi.stopChat)
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveOlder = resolve;
        }),
      )
      .mockResolvedValueOnce({ stopped: false });
    const { result } = renderHook(() => useStopFeedback("session-a"));
    let older!: Promise<{ stopped: boolean }>;
    act(() => {
      older = result.current.requestStop("chat-a");
    });
    await act(async () => {
      await result.current.requestStop("chat-a");
    });
    await act(async () => {
      resolveOlder({ stopped: true });
      await older;
    });
    expect(result.current.notice?.props.message).toContain(
      "trustedEvidence.stop.notRunning",
    );
  });
});
