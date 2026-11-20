const API_BASE_URL = (import.meta.env.VITE_COPAW_API_BASE_URL || "/copaw-api/api").replace(/\/$/, "");

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
  mcp_boundary: {
    production_guards: boolean;
    declared_host_count: number;
    endpoint_policy?: "exact" | "invalid";
    declared_endpoint_count?: number;
  };
}
export interface AdmissionEvidence {
  queried_at: string;
  mcp: ProtectionEvidence["mcp_boundary"];
  tools: { name: string; policy: "read_scope" | "bounded_artifact" | "operator_read_classification" }[];
  script_candidates: string[];
}
export interface MCPAdmissionCheck {
  checked_at: string;
  state: "ready" | "host_policy" | "guards_disabled" | "invalid_policy" | "no_exact_policy";
  cases: { case: "registered" | "default_host" | "unregistered"; transport: string; expected: "allow" | "deny"; decision: "allow" | "deny" }[];
}
export interface RedactionCheck {
  checked_at: string;
  active: boolean;
  results: {
    label: string;
    input: string;
    output: string;
    hit_ids: string[];
    changed: boolean;
  }[];
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
  subject?: string;
  execution_result?: string;
  call_id?: string;
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
export class SecurityEvidenceError extends Error {
  constructor(readonly status: number) {
    super(status === 401 || status === 403 ? "安全取证需要已验证的管理员会话。"
      : status === 404 ? "当前后端未提供安全取证接口，请核对部署版本。"
      : "无法读取安全取证数据，请稍后重试。");
  }
}

async function requestEvidence<T>(path: string, method: "GET" | "POST", signal?: AbortSignal): Promise<T> {
  // Use the same SSO-aware fetch and backend route as other Portal features.
  const response = await fetch(`${API_BASE_URL}/security/evidence/${path}`, {
    method,
    cache: "no-store",
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000),
  });
  if (!response.ok) throw new SecurityEvidenceError(response.status);
  return response.json();
}

export const securityEvidenceApi = {
  protection: (signal: AbortSignal) => requestEvidence<ProtectionEvidence>("protection", "GET", signal),
  admission: (signal: AbortSignal) => requestEvidence<AdmissionEvidence>("admission", "GET", signal),
  checkMCPAdmission: (includeHost = false) => requestEvidence<MCPAdmissionCheck>(`mcp-admission-check${includeHost ? "?include_host=true" : ""}`, "GET"),
  checkRedaction: () => requestEvidence<RedactionCheck>("redaction-check", "POST"),
  audit: (filters: Record<string, string | number>, signal: AbortSignal) => {
    const query = new URLSearchParams(Object.entries(filters).map(([key, value]) => [key, String(value)]));
    return requestEvidence<AuditPage>(`audit?${query}`, "GET", signal);
  },
};
