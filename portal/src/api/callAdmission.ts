const API_BASE = (import.meta.env.VITE_COPAW_API_BASE_URL || "/copaw-api/api").replace(/\/$/, "");

export type AdmissionKind = "tool" | "script" | "api" | "mcp_service" | "mcp_tool";
export type AdmissionRisk = "low" | "medium" | "high" | "critical";
export type AdmissionDecision = "inherit" | "deny";
export interface AdmissionTarget { kind: AdmissionKind; name: string; service: string }
export interface AdmissionChange extends AdmissionTarget {
  risk: AdmissionRisk;
  decision: AdmissionDecision;
  revision: number;
  reason: string;
}
export interface AdmissionPolicyRow extends AdmissionTarget {
  id: string;
  boundary: string;
  default_risk: AdmissionRisk;
  risk: AdmissionRisk;
  risk_source: "baseline" | "manual";
  decision: AdmissionDecision;
  revision: number;
  reason: string | null;
  updated_at: string | null;
}
export interface AdmissionPolicies { production_guards: boolean; items: AdmissionPolicyRow[] }
export interface AdmissionPolicyCheck {
  decision: AdmissionDecision | "inactive";
  checked_at: string;
  blocked_by: string | null;
}

async function request<T>(path: string, method: string, body?: object, signal?: AbortSignal): Promise<T> {
  const timeout = AbortSignal.timeout(15000);
  const response = await fetch(`${API_BASE}/security/call-admission${path}`, {
    method,
    cache: "no-store",
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    ...(body && { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  if (response.ok) return response.json();
  if (response.status === 409 || response.status === 422 || response.status === 503) {
    const data = await response.json().catch(() => null);
    if (typeof data?.detail === "string") throw new Error(data.detail);
  }
  throw new Error(response.status === 401 || response.status === 403 ? "需要已验证的管理员会话和受信请求来源。"
    : response.status === 404 ? "当前后端尚未提供调用准入控制，请核对部署版本。"
    : response.status === 422 ? "配置无效，请核对标识、风险等级和变更理由。"
    : method === "PUT" ? "未能确认保存结果，请刷新后再操作。" : "未能读取调用准入策略，请重试。");
}

export const callAdmissionApi = {
  list: (signal: AbortSignal) => request<AdmissionPolicies>("", "GET", undefined, signal),
  save: (change: AdmissionChange) => request<AdmissionPolicyRow>("", "PUT", change),
  check: ({ kind, name, service }: AdmissionTarget) => request<AdmissionPolicyCheck>("/check", "POST", { kind, name, service }),
};
