const BASE = (import.meta.env.VITE_COPAW_API_BASE_URL || "/copaw-api/api").replace(/\/$/, "")
  + "/console/chat/control/incidents";

export const riskLabels = {
  unauthorized_execution: "越权执行风险",
  unauthorized_network: "违规联网风险",
  data_exposure: "数据泄露风险",
  other_risk: "其他安全风险",
} as const;
export type IncidentRisk = keyof typeof riskLabels;

export interface IncidentBatch {
  id: string;
  at: number;
  reason: IncidentRisk | "maintenance";
  actor: string | null;
  elapsed_ms: number | null;
  total: number | null;
  counts: Record<string, number>;
  resume: { at: number; actor: string | null } | null;
}

interface IncidentPage {
  enabled: true;
  paused: boolean;
  active_count: number;
  latest: IncidentBatch | null;
  records: IncidentBatch[];
  total: number;
  page_size: number;
  retention_limit: number;
  queried_at: number;
}

export type IncidentView = IncidentPage | { enabled: false };
export interface IncidentTask {
  chat_id: string;
  agent_id: string | null;
  turn_id: string | null;
  status: string;
  started_at: number | null;
  finished_at: number | null;
  checkpoint_saved: boolean | null;
}
export interface IncidentDetail {
  batch: IncidentBatch;
  tasks: IncidentTask[];
  page_size: number;
}

async function request<T>(path: string, { signal, body }: { signal?: AbortSignal; body?: object } = {}): Promise<T> {
  const timeout = AbortSignal.timeout(20000);
  const response = await fetch(`${BASE}${path}`, {
    cache: "no-store",
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    ...(body && { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  if (response.ok) return response.json();
  if (response.status === 409) {
    const data = await response.json().catch(() => null);
    if (typeof data?.detail === "string") throw new Error(data.detail);
  }
  throw new Error(response.status === 401 || response.status === 403 ? "此操作仅限经验证的 AI 管理员，请核对会话和请求来源。"
    : response.status === 404 ? "处置记录不存在，或当前后端未启用异常中止接口。"
    : body ? "未能确认操作结果。请先刷新状态，不要重复提交。" : "无法读取异常中止状态，请刷新重试。");
}

export const portalIncidentsApi = {
  list: (page: number, signal: AbortSignal) => request<IncidentView>(`?page=${page}`, { signal }),
  detail: (batchId: string, page: number, signal: AbortSignal) => request<IncidentDetail>(`/${encodeURIComponent(batchId)}?page=${page}`, { signal }),
  stop: (reason: IncidentRisk) => request<IncidentView>("/stop", { body: { reason } }),
  resume: (batchId: string) => request<IncidentView>("/resume", { body: { batch_id: batchId, confirm: "确认复核并恢复" } }),
};
