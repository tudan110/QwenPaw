import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { securityEvidenceApi } from "@/api/modules/securityEvidence";
import { ProtectionEvidence } from "./ProtectionEvidence";
import { AuditEvidence } from "./AuditEvidence";

vi.mock("@/api/modules/securityEvidence", () => ({
  securityEvidenceApi: {
    protection: vi.fn(),
    audit: vi.fn(),
  },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback || key,
  }),
}));

describe("read-only security evidence views", () => {
  beforeEach(() => vi.clearAllMocks());
  it("shows the current redaction configuration without a sample check", async () => {
    vi.mocked(securityEvidenceApi.protection).mockResolvedValue({
      queried_at: "2026-11-17T08:00:00Z",
      output_guard: {
        enabled: false,
        mode: "off",
        active: false,
        mask_streaming: true,
        lexicon: "bundled",
        patterns: [],
      },
      mcp_boundary: { production_guards: false, declared_host_count: 0 },
    });
    render(
      <MemoryRouter>
        <ProtectionEvidence />
      </MemoryRouter>,
    );
    await screen.findByText("off");
    expect(screen.getByText("Output redaction")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run sample check" })).not.toBeInTheDocument();
  });
  it("shows a read error without inventing a successful empty audit result", async () => {
    vi.mocked(securityEvidenceApi.audit).mockRejectedValue(new Error("403"));
    render(<AuditEvidence />);
    expect(
      await screen.findByText("trustedEvidence.adminReadError"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Export displayed page" }),
    ).toBeDisabled();
    expect(screen.queryByText(/governance\/audit.db/)).not.toBeInTheDocument();
  });
  it("labels permissions separately from execution results and queries only applied filters", async () => {
    vi.mocked(securityEvidenceApi.audit).mockResolvedValue({
      records: [
        {
          rowid: 1,
          ts: 1794892800000,
          agent_id: "agent-a",
          session_id: "session-a",
          tool_name: "read_file",
          target: "/safe/file",
          decision: "allow",
          reason: "Matched policy",
        },
      ],
      total: 1,
      storage_status: "available",
      queried_at: "2026-11-17T08:00:00Z",
      source: "governance/audit.db",
      record_kind: "policy_decision",
      execution_result: "not_recorded",
    });
    render(<AuditEvidence />);
    await screen.findByText("/safe/file");
    expect(
      screen.getByText(/Execution result: not recorded/),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Agent ID" }), {
      target: { value: "agent-b" },
    });
    expect(securityEvidenceApi.audit).toHaveBeenCalledTimes(1);
    const queryButton = await screen.findByRole("button", { name: /Query$/ });
    await waitFor(() => expect(queryButton).not.toHaveClass("ant-btn-loading"));
    fireEvent.click(queryButton);
    await waitFor(() =>
      expect(securityEvidenceApi.audit).toHaveBeenLastCalledWith({
        agent_id: "agent-b",
        limit: 50,
        offset: 0,
      }),
    );
  });
});
