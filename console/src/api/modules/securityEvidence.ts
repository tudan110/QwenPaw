import { request } from "../request";

export interface ProtectionEvidence {
  queried_at: string;
  output_guard: {
    enabled: boolean;
    mode: string;
    active: boolean;
    mask_streaming: boolean;
    lexicon: string;
    patterns: { id: string; enabled: boolean }[];
  };
  mcp_boundary: { production_guards: boolean; declared_host_count: number };
}
export interface AuditRecord {
  rowid: number;
  ts: number;
  agent_id: string;
  session_id: string;
  tool_name: string;
  target: string;
  decision: string;
  reason: string;
}
export interface AuditPage {
  records: AuditRecord[];
  total: number;
  storage_status: "available" | "not_created" | "unsupported_schema";
  queried_at: string;
  source: string;
  record_kind: string;
  execution_result: string;
}
export const securityEvidenceApi = {
  protection: () =>
    request<ProtectionEvidence>("/security/evidence/protection"),
  audit: (filters: Record<string, string | number>) =>
    request<AuditPage>(
      `/security/evidence/audit?${new URLSearchParams(
        Object.entries(filters).map(([key, value]) => [key, String(value)]),
      )}`,
    ),
};
