import { requestPortalApi } from "./portalWorkorders";
import type { AlarmQueryScope } from "./alarmQueryScope";

export interface PortalRealAlarmItem {
  id: string;
  resId: string;
  title: string;
  level: "critical" | "urgent" | "warning" | "info";
  status: "active";
  eventTime: string;
  eventLastTime: string;
  timeLabel: string;
  count?: number;
  deviceName: string;
  manageIp: string;
  employeeId: string;
  dispatchContent: string;
  visibleContent: string;
  additionalText?: string;
  alarmLocation?: string;
}

export interface PortalRealAlarmListResponse {
  total: number | null;
  items: PortalRealAlarmItem[];
  source: "live" | "failed" | "unavailable";
  sourceStatus?: "live" | "failed" | "unavailable";
  queryScope?: AlarmQueryScope;
  totalIsExact?: boolean;
  windowComplete?: boolean;
}

export async function listPortalRealAlarms(
  params: { limit?: number } = {},
): Promise<PortalRealAlarmListResponse> {
  const searchParams = new URLSearchParams();
  if (params.limit !== undefined) {
    searchParams.set("limit", String(params.limit));
  }
  return requestPortalApi<PortalRealAlarmListResponse>(
    `/real-alarms${searchParams.toString() ? `?${searchParams.toString()}` : ""}`,
  );
}
