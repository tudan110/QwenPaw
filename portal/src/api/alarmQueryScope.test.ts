import assert from "node:assert/strict";
import test from "node:test";
import { alarmWindowCount, formatAlarmQueryScope } from "./alarmQueryScope.ts";

test("failed or missing totals never become zero", () => {
  assert.equal(alarmWindowCount(undefined, "live"), null);
  assert.equal(alarmWindowCount(null, "live"), null);
  assert.equal(alarmWindowCount(0, "failed"), null);
  assert.equal(alarmWindowCount(5, undefined), null);
  assert.equal(alarmWindowCount(0, "live"), 0);
  assert.equal(alarmWindowCount(5954, "live"), 5954);
});

test("window labels expose exact dates, timezone and global incompleteness", () => {
  const label = formatAlarmQueryScope({
    kind: "windowed_uncleared",
    startTime: "2026-11-11 10:00:00",
    endTime: "2026-11-12 10:00:00",
    timezone: "UTC+08:00",
    complete: false,
  });
  assert.match(label, /2026-11-11 10:00:00.*2026-11-12 10:00:00.*UTC\+08:00/);
  assert.match(label, /不代表全量活动告警/);
  assert.match(label, /空结果不能证明系统健康/);
  assert.match(formatAlarmQueryScope(), /查询时间范围未提供/);
});
