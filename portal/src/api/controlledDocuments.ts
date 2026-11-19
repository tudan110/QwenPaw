const base = (import.meta.env.VITE_COPAW_API_BASE_URL || "/copaw-api/api").replace(/\/$/, "") + "/portal/controlled-documents";

export type DocumentItem = { id: string; title: string; labels: string[]; owner: boolean; archived: boolean; created: number };
export type Preview = DocumentItem & { content: string; masked: boolean };
export type Kind = "export" | "share" | "archive";
export type Policy = { batch_cap: number; alert_limit: number; emergency: 0 | 1 };
export type Operation = {
  id: string; kind: Kind; targets: string[]; sensitive: 0 | 1; status: string; subject: string; reviewer: string | null;
  recipient_label: string | null; minutes: number | null; updated: number; expires: number; cursor: number; control_ms: number | null;
};
export type Workspace = {
  actor: string; admin: boolean; security_hold: boolean; policy: Policy; documents: DocumentItem[]; operations: Operation[];
  grants: { id: string; document_id: string; title: string; recipient_label: string; expires: number; revoked: number | null; outgoing: boolean }[];
};
export type Oversight = {
  reviews: Operation[];
  incidents: { id: string; subject: string; count: number; threshold: number; event_id: string; created: number; resolved: number | null; resolver: string | null }[];
  events: { id: string; subject: string; action: string; object_id: string; result: string; reason: string | null; created: number }[];
  revisions: { id: string; subject: string; before: Policy; after: Policy; created: number; restored_from: string | null }[];
};

async function request(path: string, options: RequestInit) {
  const response = await fetch(base + path, { ...options, cache: "no-store", signal: AbortSignal.timeout(15000) });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const message = typeof payload?.detail === "string" ? payload.detail : `请求失败（HTTP ${response.status}）`;
    throw new Error(message);
  }
  return response;
}

export const readControlled = <T,>(path: string): Promise<T> => request(path, { method: "GET" }).then((response) => response.json());
export const writeControlled = <T,>(path: string, body?: unknown): Promise<T> => request(path, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body),
}).then((response) => response.json());
export const downloadControlled = (path: string) => request(path, { method: "POST" }).then((response) => response.blob());
