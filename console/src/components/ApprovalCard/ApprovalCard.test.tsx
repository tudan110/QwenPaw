import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApprovalCard } from "./ApprovalCard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback || key,
  }),
}));
vi.mock("../../stores/agentStore", () => ({
  useAgentStore: (selector: (state: { agents: never[] }) => unknown) =>
    selector({ agents: [] }),
}));

describe("approval presentation does not change the requested operation", () => {
  it("masks the rendered and copied parameters while retaining the original request", async () => {
    const clipboard = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: clipboard },
    });
    const params = {
      path: "/safe/report.txt",
      api_key: "parameter-secret",
      url: "https://user:password@demo.invalid/private?token=url-secret",
    };
    const original = JSON.stringify(params);
    const onApprove = vi.fn().mockResolvedValue(undefined);
    const onDeny = vi.fn().mockResolvedValue(undefined);
    const { container, unmount } = render(
      <ApprovalCard
        requestId="request-a"
        toolName="read_file"
        severity="HIGH"
        findingsCount={1}
        findingsSummary="Authorization: Bearer summary-secret"
        toolParams={params}
        createdAt={Date.now() / 1000}
        timeoutSeconds={300}
        agentId="agent-a"
        exactTarget="https://user:password@demo.invalid/private?token=target-secret"
        onApprove={onApprove}
        onDeny={onDeny}
      />,
    );
    for (const secret of [
      "parameter-secret",
      "summary-secret",
      "url-secret",
      "target-secret",
      "user:password",
    ]) {
      expect(container.textContent).not.toContain(secret);
    }
    expect(container.textContent).toContain("https://demo.invalid");
    expect(container.textContent).toContain(
      "execution success must be checked separately",
    );
    const copyButtons = screen.getAllByTitle("Copy");
    fireEvent.click(copyButtons[copyButtons.length - 1]);
    await waitFor(() => expect(clipboard).toHaveBeenCalled());
    expect(clipboard.mock.calls[0][0]).toContain("/safe/report.txt");
    expect(clipboard.mock.calls[0][0]).not.toContain("parameter-secret");
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() =>
      expect(onApprove).toHaveBeenCalledWith("request-a", undefined),
    );
    expect(JSON.stringify(params)).toBe(original);
    expect(onDeny).not.toHaveBeenCalled();
    unmount();
  });
});
