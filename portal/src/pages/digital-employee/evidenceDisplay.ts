/** Presentation only. Never feed the masked result back into execution/config. */
export function endpointOrigin(value: string): string {
  try {
    const url = new URL(value);
    return `${url.protocol}//${url.host}`;
  } catch {
    return "[hidden]";
  }
}

function approvalUrl(value: string): string {
  try {
    const url = new URL(value);
    // The path can determine the approval scope. Keep it visible while
    // dropping embedded credentials, query values and fragments.
    return `${url.protocol}//${url.host}${url.pathname}${
      url.search ? "?[hidden]" : ""
    }${url.hash ? "#[hidden]" : ""}`;
  } catch {
    return "[hidden]";
  }
}

export function safeDisplayText(value: string): string {
  return value
    .replace(
      /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g,
      "[hidden]",
    )
    .replace(/[a-zA-Z][a-zA-Z0-9+.-]*:\/\/[^\s<>"']+/g, approvalUrl)
    .replace(/\b(?:Bearer|Basic)\s+\S+/gi, "[hidden]")
    .replace(
      /([\w-]*(?:token|password|passwd|secret|api[_-]?key|access[_-]?key|credential|cookie|authorization)[\w-]*["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)/gi,
      "$1[hidden]",
    )
    .replace(
      /(--?[\w-]*(?:token|password|passwd|secret|api[_-]?key|access[_-]?key|credential)[\w-]*\s+)(?:"[^"]*"|'[^']*'|\S+)/gi,
      "$1[hidden]",
    )
    .replace(/\b(?:sk-|gh[pousr]_)[A-Za-z0-9_-]{16,}/g, "[hidden]")
    .replace(
      /\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g,
      "[hidden]",
    );
}

export function auditCsvCell(value: unknown): string {
  const text = String(value ?? "");
  // Spreadsheets must treat exported event text as data, not formulas.
  const escaped = /^[\s]*[=+\-@\t\r\n]/.test(text) ? `'${text}` : text;
  return `"${escaped.replace(/"/g, '""')}"`;
}

export type StopStatus = "requesting" | "accepted" | "notRunning" | "failed" | "unavailable";

export interface StopFeedback {
  agentId: string | null;
  chatId: string;
  at: number;
  status: StopStatus;
}

export const STOP_LABELS: Record<StopStatus, string> = {
  requesting: "正在请求停止",
  accepted: "服务端已接受本地任务取消请求",
  notRunning: "服务端未找到可取消的本地运行任务",
  failed: "停止请求失败，任务状态待核实",
  unavailable: "已停止页面接收，未能向服务端提交取消请求",
};

export function stopResult(response: { stopped?: unknown } | null | undefined): StopStatus {
  if (response?.stopped === true) return "accepted";
  if (response?.stopped === false) return "notRunning";
  return "failed";
}
