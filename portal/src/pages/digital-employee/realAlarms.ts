import type {
  PortalRealAlarmItem,
  PortalRealAlarmListResponse,
} from "../../api/portalRealAlarms";

export const PORTAL_REAL_ALARM_POLL_INTERVAL_MS = 15000;

type PortalBellAlert = {
  id: string;
  employeeId: string;
  level: "critical" | "urgent" | "warning" | "info";
  message: string;
  timeLabel: string;
  routeEntry?: string | null;
  dispatchContent?: string;
  visibleContent?: string;
};

function toAlertMessage(item: PortalRealAlarmItem) {
  return `${item.title} · ${item.deviceName} · ${item.manageIp}`;
}

export function normalizePortalBellAlerts(
  response: PortalRealAlarmListResponse,
): PortalBellAlert[] {
  const seen = new Set<string>();
  const items = Array.isArray(response.items) ? response.items : [];

  return items
    .filter((item) => {
      if (!item?.id || seen.has(item.id)) {
        return false;
      }
      seen.add(item.id);
      return true;
    })
    .map((item) => ({
      id: item.id,
      employeeId: item.employeeId || "fault",
      level: item.level,
      message: toAlertMessage(item),
      timeLabel: item.timeLabel || item.eventTime,
      routeEntry: null,
      dispatchContent: item.dispatchContent,
      visibleContent: item.visibleContent,
    }));
}
