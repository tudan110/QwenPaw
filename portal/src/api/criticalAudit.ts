const API = `${(import.meta.env.VITE_COPAW_API_BASE_URL || "/copaw-api/api").replace(/\/$/, "")}/security/evidence/critical-audit`;

export type AuditKind = "policy_decision" | "tool_execution" | "governance_activity";
export interface CriticalAuditFilters {
  kind?: string;
  subject?: string;
  operation?: string;
  result?: string;
  since?: number;
  until?: number;
  before_id?: number;
  through_id?: number;
}
export interface CriticalAuditRecord {
  id: number;
  ts: number | null;
  subject: string;
  subject_kind: "account" | "agent" | "unknown" | "anonymous";
  kind: AuditKind;
  operation: string;
  target: string;
  result: string;
  decision: string | null;
  http_status: number | null;
  call_id: string | null;
}
export interface AuditStorage {
  state: "protected" | "unsealed" | "not_created" | "unsupported_schema" | "protection_missing" | "tail_mismatch";
  sealed_at?: string;
  legacy_through?: number;
}
export interface CriticalAuditPage {
  records: CriticalAuditRecord[];
  next_before_id: number | null;
  through_id: number;
  storage: AuditStorage;
  retention: { minimum_months: number; extended_months: number; valid_configuration: boolean;
    local_auto_purge: boolean; archive_status: "not_verified" };
}
export interface AuditVerification extends Omit<AuditStorage, "state"> {
  state: AuditStorage["state"] | "mismatch" | "checkpoint_mismatch" | "verified";
  checked_at: string;
  checked_events: number;
  external_match: boolean | null;
  first_bad_id?: number;
  checkpoint?: string;
}

async function request(path: string, signal: AbortSignal, body?: object, timeout = 15_000) {
  const response = await fetch(`${API}${path}`, {
    cache: "no-store",
    signal: AbortSignal.any([signal, AbortSignal.timeout(timeout)]),
    ...(body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) throw new Error(response.status === 401 || response.status === 403
    ? "此功能仅向已验证的管理员开放。"
    : response.status === 404 ? "当前后端未部署关键活动审计接口。"
      : response.status === 422 ? "筛选条件或校验锚点无效。"
        : response.status === 429 ? "已有校验正在执行，请稍后再试。"
          : "审计服务暂不可用，请稍后重试或联系运维。");
  return response;
}

export const criticalAuditApi = {
  async list(filters: CriticalAuditFilters, signal: AbortSignal): Promise<CriticalAuditPage> {
    const params = new URLSearchParams(Object.entries(filters).map(([key, value]) => [key, String(value)]));
    return (await request(`?${params}`, signal)).json();
  },
  async verify(checkpoint: string, signal: AbortSignal): Promise<AuditVerification> {
    return (await request("/verify", signal, checkpoint ? { checkpoint } : {}, 120_000)).json();
  },
  async export(filters: CriticalAuditFilters, signal: AbortSignal): Promise<Blob> {
    return (await request("/export", signal, filters)).blob();
  },
};
