export interface AlarmQueryScope {
  kind: "windowed_uncleared" | "windowed_cleared" | "windowed_history" | "unavailable";
  startTime?: string;
  endTime?: string;
  timezone?: string;
  complete: false;
  limitation?: string;
}

export function alarmWindowCount(
  total: number | null | undefined,
  sourceStatus: string | undefined,
): number | null {
  return sourceStatus === "live" &&
    typeof total === "number" &&
    Number.isFinite(total) &&
    total >= 0
    ? total
    : null;
}

export function formatAlarmQueryScope(scope?: AlarmQueryScope | null): string {
  const range = scope?.startTime && scope?.endTime
    ? `${scope.startTime} — ${scope.endTime} (${scope.timezone || "时区未提供"})`
    : "查询时间范围未提供";
  return `${range}；仅查询窗口，不代表全量活动告警；空结果不能证明系统健康。`;
}
