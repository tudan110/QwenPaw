const API_BASE_URL = (import.meta.env.VITE_COPAW_API_BASE_URL || "/copaw-api/api").replace(/\/$/, "");

export type ScanMode = "block" | "warn" | "off";
export type BoundaryKey = "tool_guard" | "skill_scan" | "domain_guard" | "output_masking" | "chat_isolation" | "text_guard" | "controlled_documents" | "controlled_workspace_files" | "mcp_remote";
export interface McpRemoteEndpoint { transport: "sse" | "streamable_http"; url: string }
export type BoundaryValue = boolean | ScanMode | McpRemoteEndpoint[];
export interface BoundaryControl { value: BoundaryValue | null; locked_reason: string | null }
export const boundaryConfirmation = "确认变更安全边界";

export interface DeleteProtection {
  blocked: boolean;
  source: "environment" | "config_or_default" | "fail_closed";
  editable?: boolean;
  locked_reason?: string | null;
}
export interface BoundarySnapshot {
  queried_at: string;
  scope: "current_backend_configuration";
  delete_protection: DeleteProtection;
  controls?: Partial<Record<BoundaryKey, BoundaryControl>>;
  mcp: {
    production_guards: boolean;
    endpoint_policy?: "exact" | "invalid";
    declared_endpoint_count?: number;
    declared_host_count: number;
  };
  tool_guard: { enabled: boolean; auto_deny_rule_count: number };
  output_masking_active: boolean;
  chat_isolation_enabled: boolean;
  text_guard_configured: boolean;
  controlled_documents_configured: boolean;
  global_skill_scan_mode: ScanMode;
  domain_guard_mode: ScanMode;
}
export interface DeletePolicyCheck {
  checked_at: string;
  scope: "knowledge_base_policy_only";
  decision: "blocked" | "not_blocked";
}

export const deleteProtectionConfirmation = (blocked: boolean) => blocked ? "启用全局删除保护" : "解除全局删除保护";

async function request<T>(path: string, signal?: AbortSignal, body?: object): Promise<T> {
  const timeout = AbortSignal.timeout(15000);
  const response = await fetch(`${API_BASE_URL}/security/boundaries${path}`, {
    cache: "no-store",
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    ...(body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
  });
  if (response.ok) return response.json();
  if (response.status === 409) {
    const data = await response.json().catch(() => null);
    if (typeof data?.detail === "string") throw new Error(data.detail);
  }
  throw new Error(response.status === 401 || response.status === 403 ? "需要已验证的管理员会话或受信请求来源。"
    : response.status === 404 ? "当前后端尚未提供安全边界接口，请核对部署版本。"
    : body ? "未能确认变更结果，请先刷新状态，不要重复提交。" : "无法读取当前安全边界，请刷新重试。");
}

export const securityBoundariesApi = {
  snapshot: (signal: AbortSignal) => request<BoundarySnapshot>("", signal),
  configure: (signal: AbortSignal, key: BoundaryKey, value: BoundaryValue, expected: BoundaryValue | null, confirm: string) =>
    request<{ changed: boolean }>(`/settings/${key}/configure`, signal, { value, expected, confirm }),
  verifyDeletion: (signal: AbortSignal) => request<DeletePolicyCheck>("/delete-protection/check", signal),
  configureDeletion: (signal: AbortSignal, blocked: boolean, expectedBlocked: boolean, confirm: string) =>
    request<{ delete_protection: DeleteProtection; changed: boolean }>(
      "/delete-protection/configure", signal, { blocked, expected_blocked: expectedBlocked, confirm },
    ),
};
