import type { TraceEvent } from "../../api/traces";

export type CheckKind = "权限校验" | "工具调用" | "执行异常" | "输出防护";

export interface TraceCheck {
  kind: CheckKind;
  target: string;
  status: string;
  severity: "normal" | "notice" | "risk";
  reference: string;
  ts: number;
  agent: string;
}

/** Summarize only structured facts; never copy arguments, output or exception text. */
export function traceChecks(events: TraceEvent[]): TraceCheck[] {
  return events.flatMap((event): TraceCheck[] => {
    const base = { ts: event.ts, agent: event.agent_id || "—" };
    if (event.type === "authorization") {
      const decision = String(event.decision || "");
      const status = { allow: "已允许", deny: "已拒绝", pending: "待确认", unconfirmed: "未确认" }[decision] || "未知决定";
      return [{ ...base, kind: "权限校验", target: String(event.target || "—"), status,
        severity: decision === "deny" ? "risk" : decision === "allow" ? "normal" : "notice",
        reference: String(event.authorization_id || "") }];
    }
    if (event.type === "tool_call") {
      const outcome = event.outcome || "";
      const state = { ok: "成功", error: "失败", denied: "拒绝执行", auto_denied: "自动拒绝", timeout: "超时" }[outcome];
      return [{ ...base, kind: "工具调用", target: event.tool_name || "—", status: state || "未记录结果",
        severity: outcome === "ok" ? "normal" : state ? "risk" : "notice", reference: event.tool_call_id || "" }];
    }
    if (event.type === "error" || (event.type === "llm_call" && event.status && event.status !== "ok")) {
      return [{ ...base, kind: "执行异常", target: event.type === "llm_call" ? "模型请求" : "智能体执行",
        status: event.type === "llm_call" ? `请求状态：${event.status}` : "已记录执行异常", severity: "risk", reference: "" }];
    }
    // Future typed output defense events may be shown, but tool-guard findings
    // and an ordinary model reply are not evidence of an output violation.
    if (event.type === "output_guard" && (event.outcome === "denied" || event.action === "redacted")) {
      return [{ ...base, kind: "输出防护", target: "模型回复", status: event.outcome === "denied" ? "已拦截" : "已脱敏",
        severity: "risk", reference: "" }];
    }
    return [];
  });
}

export function reviewExpired(day: string, now = new Date()): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return false;
  const today = [now.getFullYear(), now.getMonth() + 1, now.getDate()]
    .map((value) => String(value).padStart(2, "0")).join("-");
  return day < today;
}

export const syntheticData = {
  "联系人": "示例联系人甲",
  "电话": "000-1234-5678（虚构）",
  "邮箱": "agent-demo@example.invalid",
  "资产编号": "DEMO-ASSET-001",
};

export function previewSensitiveData(mode: string) {
  if (mode === "omit") return { "资产编号": syntheticData.资产编号 };
  return { ...syntheticData, "联系人": "示**", "电话": "***-****-5678", "邮箱": "a***@example.invalid" };
}
