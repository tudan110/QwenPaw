import { requestPortalApi } from "./portalWorkorders";

export type AlarmExportSelection =
  | { source: "registry"; status?: string; search?: string }
  | { source: "live"; begin_time: string; end_time: string; is_clear: "0" | "1";
      severity?: string; keyword?: string; manage_ip?: string; resource_type?: string };

export interface AlarmExportPreview {
  count: number;
  max_rows: number;
  message: string;
  ticket?: string;
}

type ExportPolicy = { max_rows: number };

function send<T>(path: string, method: "POST" | "PUT", body: object) {
  return requestPortalApi<T>(path, {
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }, 40_000);
}

export const alarmExportApi = {
  preview: (selection: AlarmExportSelection) =>
    send<AlarmExportPreview>("/alarm-export/preview", "POST", selection),
  download: (selection: AlarmExportSelection, ticket: string) =>
    send<{ total: number; items: unknown[] }>("/alarm-export/download", "POST", { selection, ticket }),
  getPolicy: (signal?: AbortSignal) => requestPortalApi<ExportPolicy>("/alarm-export-settings", { signal }),
  savePolicy: (limit: number) => send<ExportPolicy>("/alarm-export-settings", "PUT", { max_rows: limit }),
};

export function parseAlarmExportLink(href: string): AlarmExportSelection | null {
  if (!/^\/(?:api\/portal|portal-api)\/alarm-export\/preview\?/.test(href)) return null;
  const params = new URLSearchParams(href.slice(href.indexOf("?") + 1));
  const begin_time = params.get("begin_time");
  const end_time = params.get("end_time");
  const is_clear = params.get("is_clear");
  const allowed = ["source", "begin_time", "end_time", "is_clear", "severity", "keyword", "manage_ip", "resource_type"];
  if (params.get("source") !== "live" || !begin_time || !end_time
    || (is_clear !== "0" && is_clear !== "1")
    || [...params.keys()].some((key) => !allowed.includes(key) || params.getAll(key).length !== 1)) return null;
  return { source: "live", begin_time, end_time, is_clear, severity: params.get("severity") ?? undefined,
    keyword: params.get("keyword") ?? undefined, manage_ip: params.get("manage_ip") ?? undefined,
    resource_type: params.get("resource_type") ?? undefined };
}
