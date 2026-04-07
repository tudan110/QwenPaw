import type { AlarmWorkorder } from "../types/portal";

const DEFAULT_PORTAL_API_BASE_URL = "/portal-api";
const DEFAULT_REQUEST_TIMEOUT_MS = 15000;

const PORTAL_API_BASE_URL = (
  import.meta.env.VITE_PORTAL_API_BASE_URL || DEFAULT_PORTAL_API_BASE_URL
).replace(/\/$/, "");

export interface AlarmWorkorderListResponse {
  total?: number;
  items?: AlarmWorkorder[];
  source?: string;
}

async function requestPortalApi<T = unknown>(
  path: string,
  init: RequestInit = {},
  timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timerId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${PORTAL_API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
    });

    if (!response.ok) {
      const errorText = await response.text().catch(() => "");
      throw new Error(errorText || "Portal 请求失败");
    }

    return response.json();
  } catch (error: any) {
    if (error?.name === "AbortError") {
      throw new Error("请求超时，请稍后重试");
    }
    throw error;
  } finally {
    window.clearTimeout(timerId);
  }
}

export async function listAlarmWorkorders(
  params: { limit?: number } = {},
): Promise<AlarmWorkorderListResponse | AlarmWorkorder[]> {
  const searchParams = new URLSearchParams();
  if (params.limit) {
    searchParams.set("limit", String(params.limit));
  }

  return requestPortalApi<AlarmWorkorderListResponse | AlarmWorkorder[]>(
    `/alarm-workorders${
      searchParams.toString() ? `?${searchParams.toString()}` : ""
    }`,
  );
}

export async function killSlowSqlSession(
  payload: Record<string, unknown> = {},
): Promise<Record<string, unknown>> {
  return requestPortalApi<Record<string, unknown>>("/mock/kill-slow-sql", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}
