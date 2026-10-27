import type {
  ApprovalScope,
  MainChatApproval,
} from "../pages/digital-employee/mainChatApproval";

const API_BASE_URL = (import.meta.env.VITE_COPAW_API_BASE_URL || "/copaw-api/api")
  .replace(/\/$/, "");

export class MainChatApprovalApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "MainChatApprovalApiError";
  }
}

export function isMissingApprovalRequest(error: unknown): boolean {
  return error instanceof MainChatApprovalApiError
    && error.status === 404
    && /^Approval request not found(?::|$)/i.test(error.message);
}

async function approvalRequest<T>(
  path: string,
  agentId: string,
  signal: AbortSignal,
  body?: Record<string, unknown>,
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: body ? "POST" : "GET",
    headers: {
      "X-Agent-Id": agentId,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    signal,
    cache: "no-store",
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) {
    const text = await response.text();
    let detail = text;
    try {
      const payload = JSON.parse(text);
      detail = typeof payload.detail === "string" ? payload.detail : text;
    } catch {
      // Non-JSON errors retain the server's original message.
    }
    throw new MainChatApprovalApiError(
      detail || `审批请求失败（${response.status}）`,
      response.status,
    );
  }
  return response.json();
}

export async function listMainChatApprovals(
  agentId: string,
  sessionId: string,
  signal: AbortSignal,
): Promise<MainChatApproval[]> {
  if (!agentId || !sessionId) {
    throw new Error("缺少智能体或会话信息，无法获取审批请求。");
  }
  const response = await approvalRequest<{ pending_approvals: MainChatApproval[] }>(
    `/approval/list?session_id=${encodeURIComponent(sessionId)}`,
    agentId,
    signal,
  );
  if (!Array.isArray(response.pending_approvals)) {
    throw new Error("审批列表格式异常，请稍后重试。");
  }
  return response.pending_approvals;
}

export async function resolveMainChatApproval(
  agentId: string,
  sessionId: string,
  requestId: string,
  action: "approve" | "deny",
  signal: AbortSignal,
  scope: ApprovalScope = "exact",
): Promise<void> {
  const response = await approvalRequest<{ success: boolean; message?: string }>(
    `/approval/${action}`,
    agentId,
    signal,
    {
      request_id: requestId,
      session_id: sessionId,
      ...(action === "approve" ? { scope } : {}),
    },
  );
  if (response.success !== true) {
    throw new Error(response.message || "审批操作未成功，请重试。");
  }
}

export async function stopMainChatApprovalTask(
  agentId: string,
  chatId: string,
  signal: AbortSignal,
): Promise<void> {
  const response = await approvalRequest<{ stopped: boolean }>(
    `/console/chat/stop?chat_id=${encodeURIComponent(chatId)}`,
    agentId,
    signal,
    {},
  );
  if (response.stopped !== true) {
    throw new Error("任务未停止，请刷新状态后重试。");
  }
}
