const apiBase = (import.meta.env.VITE_COPAW_API_BASE_URL || "/copaw-api/api").replace(/\/$/, "");

async function request<T>(path: string, signal: AbortSignal, init: RequestInit = {}): Promise<T> {
  const timeout = init.method === "POST" ? 120_000 : 15_000;
  const response = await fetch(`${apiBase}/security/governance/${path}`, {
    ...init, cache: "no-store", signal: AbortSignal.any([signal, AbortSignal.timeout(timeout)]),
  });
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) throw new Error("此功能需要已验证的管理员会话。");
    if (response.status === 404) throw new Error("当前后端尚未提供组件治理接口，请核对部署版本。");
    const body = await response.json().catch(() => ({}));
    throw new Error((response.status === 409 || response.status === 503) && typeof body.detail === "string"
      ? body.detail : "当前操作未完成，请稍后重试。");
  }
  return response.json() as Promise<T>;
}

export type ChangeView = "supply" | "config";
export type Change = {
  id: number; timestamp: string; subject: string; scope: string; scope_name?: string; kind: string;
  target: string; action: string; fields: string[];
  before: Record<string, string | boolean> | null; after: Record<string, string | boolean> | null;
};
export type Changes = { records: Change[]; total: number; write_warning: boolean };
export type ScanStatus = "clear" | "findings" | "incomplete" | "not_covered" | "not_applicable";
export type ScanRow = {
  kind: string; name: string; scope: string; scope_name?: string; status: ScanStatus; detail: string; findings: string[];
  action?: { index: number; kind: "disable_skill" | "isolate_mcp"; done: boolean };
};
export type ScanReport = { checked_at: string; rows: ScanRow[] };
export type LocalMode = "managed" | "deny";
export type LocalPolicy = {
  mode: LocalMode; allow_downloads: boolean; running: boolean; authenticated: boolean;
  filesystem_supported: boolean; external_local_detected: boolean;
};

export const componentGovernanceApi = {
  changes: (view: ChangeView, offset: number, signal: AbortSignal) =>
    request<Changes>(`changes?view=${view}&limit=20&offset=${offset}`, signal),
  scanReport: (signal: AbortSignal) => request<{ report: ScanReport | null }>("scan", signal),
  scan: (signal: AbortSignal) => request<{ report: ScanReport }>("scan", signal, { method: "POST" }),
  disposition: (checked_at: string, index: number, signal: AbortSignal) =>
    request<{ report: ScanReport; message: string }>("scan/disposition", signal, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ checked_at, index }),
    }),
  stopLocal: (signal: AbortSignal) => request<LocalPolicy>("local-access/stop", signal, { method: "POST" }),
  localPolicy: (signal: AbortSignal) => request<LocalPolicy>("local-access", signal),
  saveLocalPolicy: (mode: LocalMode, allow_downloads: boolean, signal: AbortSignal) => request<LocalPolicy>("local-access", signal, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode, allow_downloads }),
  }),
};
