import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ExecutionControlTab } from "./ExecutionControlTab";
import { executionControlApi } from "../../../../api/modules/executionControl";

vi.mock("../../../../api/modules/executionControl", () => ({
  executionControlApi: { get: vi.fn(), archive: vi.fn(), transition: vi.fn() },
}));

describe("execution controls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(executionControlApi.get).mockResolvedValue({
      frozen: 0,
      epoch: 4,
      reason: "",
      updated_at: 0,
    });
    vi.mocked(executionControlApi.archive).mockResolvedValue({
      pending: 3,
      oldest_at: 0,
      external_retention_verified: false,
    });
  });

  it("requires a reason and submits the displayed epoch once", async () => {
    vi.mocked(executionControlApi.transition).mockResolvedValue({
      frozen: 1,
      epoch: 5,
      reason: "incident",
      updated_at: 1,
    });
    render(<ExecutionControlTab />);
    const button = await screen.findByRole("button", {
      name: "冻结执行并请求停止",
    });
    await screen.findByText("允许执行");
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText("处置说明"), {
      target: { value: "incident" },
    });
    fireEvent.click(button);
    await waitFor(() =>
      expect(executionControlApi.transition).toHaveBeenCalledExactlyOnceWith(
        true,
        4,
        "incident",
      ),
    );
  });

  it("refreshes after an ambiguous failure without repeating the action", async () => {
    vi.mocked(executionControlApi.transition).mockRejectedValue(
      new Error("请求超时"),
    );
    render(<ExecutionControlTab />);
    await screen.findByText("允许执行");
    fireEvent.change(screen.getByLabelText("处置说明"), {
      target: { value: "incident" },
    });
    fireEvent.click(screen.getByRole("button", { name: "冻结执行并请求停止" }));
    await screen.findByText("请求超时");
    expect(executionControlApi.transition).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(executionControlApi.get).toHaveBeenCalledTimes(2),
    );
  });
});
