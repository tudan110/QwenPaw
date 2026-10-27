export type MainChatApprovalLevel = "STRICT" | "SMART" | "AUTO" | "OFF" | null;
export type ApprovalScope = "exact" | "similar";

export interface MainChatApproval {
  request_id: string;
  session_id: string;
  root_session_id: string;
  agent_id: string;
  owner_agent_id?: string;
  tool_name: string;
  tool_display_name?: string;
  tool_source?: string;
  severity: string;
  findings_count: number;
  result_summary: string;
  created_at: number;
  timeout_seconds: number;
  exact_target?: string;
  similar_target?: string;
  is_generalized?: boolean;
}

export const APPROVAL_LEVELS = [
  { value: null, label: "默认模式", description: "继承当前智能体的工具执行安全级别" },
  { value: "STRICT", label: "严格模式", description: "普通工具调用也需审批，禁止操作仍会被拦截" },
  { value: "SMART", label: "智能模式", description: "结合风险与授权规则决定是否需要审批" },
  { value: "AUTO", label: "自动模式", description: "沿用后端自动策略，不代表全部自动放行" },
  { value: "OFF", label: "关闭模式", description: "关闭工具审批防护，仅用于完全可信的操作" },
] as const;

export function normalizeApprovalLevel(value: unknown): MainChatApprovalLevel {
  return APPROVAL_LEVELS.some((item) => item.value === value)
    ? value as MainChatApprovalLevel
    : null;
}

export function approvalStorageKey(userId: string, agentId: string, sessionId: string): string {
  return `portal.main-chat.approval:${JSON.stringify([userId, agentId, sessionId])}`;
}

export function withMainChatApprovalLevel<T extends Record<string, unknown>>(
  body: T,
  level: MainChatApprovalLevel,
): T {
  if (level === null) return body;
  const context = body.request_context;
  return {
    ...body,
    request_context: {
      ...(context && typeof context === "object" && !Array.isArray(context) ? context : {}),
      approval_level: level,
    },
  };
}

export function selectMainChatApprovals(
  approvals: MainChatApproval[],
  agentId: string,
  sessionId: string,
): MainChatApproval[] {
  return approvals
    .filter((item) =>
      item.root_session_id === sessionId
      && (item.owner_agent_id || item.agent_id) === agentId,
    )
    .sort((a, b) => a.created_at - b.created_at);
}

export function approvalRemainingSeconds(approval: MainChatApproval, now = Date.now()): number {
  return Math.max(0, Math.ceil(
    approval.created_at + approval.timeout_seconds - now / 1000,
  ));
}
