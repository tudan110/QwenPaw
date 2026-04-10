import { useCallback, useEffect, useMemo, useState } from "react";
import {
  cronJobsApi,
  type CronJobRequest,
  type CronJobSpec,
  type CronJobState,
} from "../../api/cronJobs";
import "./cronJobsPanel.css";

type JobFilter = "all" | "running" | "stopped" | "pending";
type CronType = "hourly" | "daily" | "weekly" | "custom";
type TaskType = "agent" | "text";
type DispatchMode = "final" | "stream";
type DisplayStatusKey = "running" | "pending" | "stopped";
type DisplayTone = "green" | "amber" | "red" | "slate";

type CronParts = {
  type: CronType;
  hour?: number;
  minute?: number;
  daysOfWeek?: string[];
  rawCron?: string;
};

type CronJobFormState = {
  id: string;
  name: string;
  enabled: boolean;
  taskType: TaskType;
  content: string;
  channel: string;
  targetUser: string;
  targetSession: string;
  mode: DispatchMode;
  timezone: string;
  cronType: CronType;
  hour: number;
  minute: number;
  daysOfWeek: string[];
  customCron: string;
  maxConcurrency: number;
  timeoutSeconds: number;
  misfireGraceSeconds: number;
};

type DisplayStatus = {
  key: DisplayStatusKey;
  tone: DisplayTone;
  label: string;
  helper: string;
  isError: boolean;
};

type JobRecord = {
  job: CronJobSpec;
  state: CronJobState;
  status: DisplayStatus;
};

const FILTER_OPTIONS: Array<{ id: JobFilter; label: string }> = [
  { id: "all", label: "全部" },
  { id: "running", label: "运行中" },
  { id: "stopped", label: "已停止" },
  { id: "pending", label: "待执行" },
];

const ORDERED_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
const DAY_LABELS: Record<string, string> = {
  mon: "周一",
  tue: "周二",
  wed: "周三",
  thu: "周四",
  fri: "周五",
  sat: "周六",
  sun: "周日",
};
const INTEGER_RE = /^\d+$/;
const CRON_RE = /^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$/;
const DAY_NAME_SET = new Set(ORDERED_DAYS);
const NUM_TO_NAME: Record<string, (typeof ORDERED_DAYS)[number]> = {
  "0": "sun",
  "1": "mon",
  "2": "tue",
  "3": "wed",
  "4": "thu",
  "5": "fri",
  "6": "sat",
  "7": "sun",
};

function getBrowserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function createDefaultFormState(): CronJobFormState {
  return {
    id: "",
    name: "",
    enabled: true,
    taskType: "agent",
    content: "",
    channel: "console",
    targetUser: "cron",
    targetSession: "portal-cron",
    mode: "final",
    timezone: getBrowserTimezone(),
    cronType: "daily",
    hour: 9,
    minute: 0,
    daysOfWeek: ["mon"],
    customCron: "0 9 * * *",
    maxConcurrency: 1,
    timeoutSeconds: 120,
    misfireGraceSeconds: 60,
  };
}

function parsePlainCronNumber(value: string, min: number, max: number): number | null {
  if (!INTEGER_RE.test(value)) {
    return null;
  }

  const parsed = Number(value);
  if (parsed < min || parsed > max) {
    return null;
  }

  return parsed;
}

function isDayName(value: string): value is (typeof ORDERED_DAYS)[number] {
  return DAY_NAME_SET.has(value as (typeof ORDERED_DAYS)[number]);
}

function parseDaysOfWeek(dayOfWeek: string): string[] {
  const days: Array<(typeof ORDERED_DAYS)[number]> = [];
  const parts = dayOfWeek.split(",");

  for (const part of parts) {
    const trimmed = part.trim().toLowerCase();

    if (!trimmed) {
      return [];
    }

    if (isDayName(trimmed)) {
      if (!days.includes(trimmed)) {
        days.push(trimmed);
      }
      continue;
    }

    if (trimmed.includes("-")) {
      const rangeParts = trimmed.split("-");
      if (rangeParts.length !== 2) {
        return [];
      }

      const startName = NUM_TO_NAME[rangeParts[0]] || rangeParts[0];
      const endName = NUM_TO_NAME[rangeParts[1]] || rangeParts[1];
      if (!isDayName(startName) || !isDayName(endName)) {
        return [];
      }

      const startIndex = ORDERED_DAYS.indexOf(startName);
      const endIndex = ORDERED_DAYS.indexOf(endName);
      if (startIndex === -1 || endIndex === -1 || startIndex > endIndex) {
        return [];
      }

      for (let index = startIndex; index <= endIndex; index += 1) {
        if (!days.includes(ORDERED_DAYS[index])) {
          days.push(ORDERED_DAYS[index]);
        }
      }
      continue;
    }

    const normalized = NUM_TO_NAME[trimmed];
    if (!normalized) {
      return [];
    }
    if (!days.includes(normalized)) {
      days.push(normalized);
    }
  }

  return days;
}

function serializeDaysOfWeek(daysOfWeek?: string[]) {
  const selectedDays = ORDERED_DAYS.filter((day) => daysOfWeek?.includes(day));
  if (!selectedDays.length) {
    return "mon";
  }

  const segments: string[] = [];
  let rangeStart = selectedDays[0];
  let previousDay = selectedDays[0];

  for (let index = 1; index <= selectedDays.length; index += 1) {
    const currentDay = selectedDays[index];
    const isContiguous =
      currentDay !== undefined
      && ORDERED_DAYS.indexOf(currentDay) === ORDERED_DAYS.indexOf(previousDay) + 1;

    if (isContiguous) {
      previousDay = currentDay;
      continue;
    }

    if (rangeStart === previousDay) {
      segments.push(rangeStart);
    } else {
      segments.push(`${rangeStart}-${previousDay}`);
    }

    rangeStart = currentDay;
    previousDay = currentDay ?? previousDay;
  }

  return segments.join(",");
}

function parseCron(cron: string): CronParts {
  const trimmed = String(cron || "").trim();
  if (!trimmed) {
    return { type: "daily", hour: 9, minute: 0 };
  }

  const match = trimmed.match(CRON_RE);
  if (!match) {
    return { type: "custom", rawCron: trimmed };
  }

  const [, minute, hour, dayOfMonth, month, dayOfWeek] = match;

  if (
    hour === "*"
    && dayOfMonth === "*"
    && month === "*"
    && dayOfWeek === "*"
    && minute === "0"
  ) {
    return { type: "hourly", minute: 0 };
  }

  if (dayOfMonth === "*" && month === "*" && dayOfWeek === "*") {
    const parsedHour = parsePlainCronNumber(hour, 0, 23);
    const parsedMinute = parsePlainCronNumber(minute, 0, 59);
    if (parsedHour !== null && parsedMinute !== null) {
      return { type: "daily", hour: parsedHour, minute: parsedMinute };
    }
  }

  if (dayOfMonth === "*" && month === "*" && dayOfWeek !== "*") {
    const parsedHour = parsePlainCronNumber(hour, 0, 23);
    const parsedMinute = parsePlainCronNumber(minute, 0, 59);
    const daysOfWeek = parseDaysOfWeek(dayOfWeek);
    if (parsedHour !== null && parsedMinute !== null && daysOfWeek.length) {
      return {
        type: "weekly",
        hour: parsedHour,
        minute: parsedMinute,
        daysOfWeek,
      };
    }
  }

  return { type: "custom", rawCron: trimmed };
}

function serializeCron(parts: CronParts): string {
  switch (parts.type) {
    case "hourly":
      return "0 * * * *";
    case "daily":
      return `${parts.minute ?? 0} ${parts.hour ?? 9} * * *`;
    case "weekly":
      return `${parts.minute ?? 0} ${parts.hour ?? 9} * * ${serializeDaysOfWeek(parts.daysOfWeek)}`;
    case "custom":
      return String(parts.rawCron || "0 9 * * *").trim();
    default:
      return "0 9 * * *";
  }
}

function formatDateTime(value?: string | null) {
  if (!value) {
    return "-";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function extractTextFromUnknown(value: unknown): string[] {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed ? [trimmed] : [];
  }

  if (Array.isArray(value)) {
    return value.flatMap((item) => extractTextFromUnknown(item));
  }

  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (typeof record.text === "string") {
      const trimmed = record.text.trim();
      return trimmed ? [trimmed] : [];
    }
    if ("content" in record) {
      return extractTextFromUnknown(record.content);
    }
  }

  return [];
}

function extractPromptFromRequest(request?: CronJobRequest) {
  return extractTextFromUnknown(request?.input).join("\n").trim();
}

function buildAgentRequest(
  prompt: string,
  targetUser: string,
  targetSession: string,
  sourceRequest?: CronJobRequest,
): CronJobRequest {
  return {
    ...(sourceRequest || {}),
    input: [
      {
        role: "user",
        type: "message",
        content: [
          {
            type: "text",
            text: prompt,
          },
        ],
      },
    ],
    user_id: targetUser,
    session_id: targetSession,
  };
}

function createFormStateFromJob(job: CronJobSpec): CronJobFormState {
  const schedule = parseCron(job.schedule?.cron || "0 9 * * *");
  return {
    id: job.id,
    name: job.name || "",
    enabled: job.enabled !== false,
    taskType: job.task_type === "text" ? "text" : "agent",
    content: job.task_type === "text" ? String(job.text || "") : extractPromptFromRequest(job.request),
    channel: job.dispatch?.channel || "console",
    targetUser: job.dispatch?.target?.user_id || "cron",
    targetSession: job.dispatch?.target?.session_id || "portal-cron",
    mode: job.dispatch?.mode === "stream" ? "stream" : "final",
    timezone: job.schedule?.timezone || getBrowserTimezone(),
    cronType: schedule.type,
    hour: schedule.hour ?? 9,
    minute: schedule.minute ?? 0,
    daysOfWeek: schedule.daysOfWeek || ["mon"],
    customCron: schedule.rawCron || job.schedule?.cron || "0 9 * * *",
    maxConcurrency: Math.max(1, Number(job.runtime?.max_concurrency || 1)),
    timeoutSeconds: Math.max(1, Number(job.runtime?.timeout_seconds || 120)),
    misfireGraceSeconds: Math.max(0, Number(job.runtime?.misfire_grace_seconds || 60)),
  };
}

function buildPayloadFromForm(form: CronJobFormState, sourceJob: CronJobSpec | null): CronJobSpec {
  const cron = serializeCron({
    type: form.cronType,
    hour: form.hour,
    minute: form.minute,
    daysOfWeek: form.daysOfWeek,
    rawCron: form.customCron,
  });
  const content = form.content.trim();
  const targetUser = form.targetUser.trim();
  const targetSession = form.targetSession.trim();

  return {
    id: sourceJob?.id || form.id || "",
    name: form.name.trim(),
    enabled: form.enabled,
    schedule: {
      type: "cron",
      cron,
      timezone: form.timezone.trim() || "UTC",
    },
    task_type: form.taskType,
    text: form.taskType === "text" ? content : undefined,
    request:
      form.taskType === "agent"
        ? buildAgentRequest(content, targetUser, targetSession, sourceJob?.request)
        : undefined,
    dispatch: {
      type: "channel",
      channel: form.channel.trim(),
      target: {
        user_id: targetUser,
        session_id: targetSession,
      },
      mode: form.mode,
      meta: sourceJob?.dispatch?.meta || {},
    },
    runtime: {
      max_concurrency: Math.max(1, Number(form.maxConcurrency || 1)),
      timeout_seconds: Math.max(1, Number(form.timeoutSeconds || 120)),
      misfire_grace_seconds: Math.max(0, Number(form.misfireGraceSeconds || 60)),
    },
    meta: sourceJob?.meta || {},
  };
}

function resolveDisplayStatus(job: CronJobSpec, state: CronJobState): DisplayStatus {
  const enabled = job.enabled !== false;

  if (!enabled) {
    return {
      key: "stopped",
      tone: "slate",
      label: "已停用",
      helper: "不会按照计划自动执行",
      isError: false,
    };
  }

  if (state.last_status === "running") {
    return {
      key: "running",
      tone: "green",
      label: "执行中",
      helper: "任务正在后台运行",
      isError: false,
    };
  }

  if (!state.last_run_at && state.next_run_at) {
    return {
      key: "pending",
      tone: "amber",
      label: "待首次执行",
      helper: "已创建，等待首次调度",
      isError: false,
    };
  }

  if (!state.next_run_at) {
    return {
      key: "stopped",
      tone: "slate",
      label: "已暂停",
      helper: "当前没有下一次调度时间",
      isError: false,
    };
  }

  if (state.last_status === "error") {
    return {
      key: "running",
      tone: "red",
      label: "最近失败",
      helper: state.last_error || "上一次执行发生错误",
      isError: true,
    };
  }

  return {
    key: "running",
    tone: "green",
    label: "运行中",
    helper: "按计划继续调度",
    isError: false,
  };
}

function matchesFilter(record: JobRecord, filter: JobFilter) {
  if (filter === "all") {
    return true;
  }
  return record.status.key === filter;
}

function formatTaskType(job: CronJobSpec) {
  return job.task_type === "text" ? "固定消息" : "Agent 提问";
}

function formatTarget(job: CronJobSpec) {
  const channel = job.dispatch?.channel || "-";
  const targetUser = job.dispatch?.target?.user_id || "-";
  const targetSession = job.dispatch?.target?.session_id || "-";
  return `${channel} / ${targetUser} / ${targetSession}`;
}

function getCronSummary(cron: string) {
  const parsed = parseCron(cron);
  if (parsed.type === "hourly") {
    return "每小时整点";
  }
  if (parsed.type === "daily") {
    return `每天 ${String(parsed.hour ?? 0).padStart(2, "0")}:${String(parsed.minute ?? 0).padStart(2, "0")}`;
  }
  if (parsed.type === "weekly") {
    const days = (parsed.daysOfWeek || []).map((day) => DAY_LABELS[day] || day).join("、");
    return `每周 ${days} ${String(parsed.hour ?? 0).padStart(2, "0")}:${String(parsed.minute ?? 0).padStart(2, "0")}`;
  }
  return cron;
}

export function CronJobsPanel() {
  const [jobs, setJobs] = useState<CronJobSpec[]>([]);
  const [states, setStates] = useState<Record<string, CronJobState>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [actionJobId, setActionJobId] = useState("");
  const [filter, setFilter] = useState<JobFilter>("all");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingJob, setEditingJob] = useState<CronJobSpec | null>(null);
  const [formState, setFormState] = useState<CronJobFormState>(createDefaultFormState());
  const [formError, setFormError] = useState("");

  useEffect(() => {
    if (!notice) {
      return undefined;
    }
    const timer = window.setTimeout(() => setNotice(""), 2800);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const refreshJobs = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const nextJobs = await cronJobsApi.listCronJobs();
      const stateEntries = await Promise.all(
        nextJobs.map(async (job) => {
          try {
            const state = await cronJobsApi.getCronJobState(job.id);
            return [job.id, state] as const;
          } catch {
            return [job.id, {}] as const;
          }
        }),
      );
      setJobs(nextJobs);
      setStates(Object.fromEntries(stateEntries));
    } catch (loadError: any) {
      setError(loadError?.message || "定时任务加载失败，请稍后重试。");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshJobs();
  }, [refreshJobs]);

  const jobRecords = useMemo<JobRecord[]>(() => {
    return [...jobs]
      .map((job) => {
        const state = states[job.id] || {};
        return {
          job,
          state,
          status: resolveDisplayStatus(job, state),
        };
      })
      .sort((left, right) => {
        const leftTime = left.state.next_run_at
          ? new Date(left.state.next_run_at).getTime()
          : Number.MAX_SAFE_INTEGER;
        const rightTime = right.state.next_run_at
          ? new Date(right.state.next_run_at).getTime()
          : Number.MAX_SAFE_INTEGER;
        if (leftTime !== rightTime) {
          return leftTime - rightTime;
        }
        return left.job.name.localeCompare(right.job.name, "zh-CN");
      });
  }, [jobs, states]);

  const filteredJobs = useMemo(
    () => jobRecords.filter((record) => matchesFilter(record, filter)),
    [filter, jobRecords],
  );

  const stats = useMemo(() => {
    return {
      total: jobRecords.length,
      running: jobRecords.filter((record) => record.status.key === "running").length,
      pending: jobRecords.filter((record) => record.status.key === "pending").length,
      errors: jobRecords.filter((record) => record.status.isError).length,
    };
  }, [jobRecords]);

  const openCreateModal = () => {
    setEditingJob(null);
    setFormState(createDefaultFormState());
    setFormError("");
    setIsModalOpen(true);
  };

  const openEditModal = (job: CronJobSpec) => {
    setEditingJob(job);
    setFormState(createFormStateFromJob(job));
    setFormError("");
    setIsModalOpen(true);
  };

  const closeModal = () => {
    setIsModalOpen(false);
    setEditingJob(null);
    setFormError("");
  };

  const updateForm = <K extends keyof CronJobFormState>(key: K, value: CronJobFormState[K]) => {
    setFormState((prev) => ({ ...prev, [key]: value }));
  };

  const validateForm = () => {
    if (!formState.name.trim()) {
      return "请输入任务名称。";
    }
    if (!formState.channel.trim()) {
      return "请输入投递通道。";
    }
    if (!formState.targetUser.trim()) {
      return "请输入目标 user_id。";
    }
    if (!formState.targetSession.trim()) {
      return "请输入目标 session_id。";
    }
    if (!formState.content.trim()) {
      return formState.taskType === "text" ? "请输入固定消息内容。" : "请输入发送给 Agent 的问题。";
    }
    if (!formState.timezone.trim()) {
      return "请输入时区。";
    }
    if (formState.cronType === "weekly" && !formState.daysOfWeek.length) {
      return "请选择至少一个执行星期。";
    }
    const cron = serializeCron({
      type: formState.cronType,
      hour: formState.hour,
      minute: formState.minute,
      daysOfWeek: formState.daysOfWeek,
      rawCron: formState.customCron,
    });
    if (!CRON_RE.test(cron)) {
      return "Cron 表达式必须是 5 段格式，例如 0 9 * * *。";
    }
    return "";
  };

  const handleSubmit = async () => {
    const nextFormError = validateForm();
    if (nextFormError) {
      setFormError(nextFormError);
      return;
    }

    setSubmitting(true);
    setFormError("");

    try {
      const payload = buildPayloadFromForm(formState, editingJob);
      if (editingJob) {
        await cronJobsApi.replaceCronJob(editingJob.id, payload);
        setNotice(`已更新任务“${payload.name}”。`);
      } else {
        await cronJobsApi.createCronJob(payload);
        setNotice(`已创建任务“${payload.name}”。`);
      }
      closeModal();
      await refreshJobs();
    } catch (submitError: any) {
      setFormError(submitError?.message || "保存失败，请稍后重试。");
    } finally {
      setSubmitting(false);
    }
  };

  const runJobAction = async (
    jobId: string,
    action: () => Promise<unknown>,
    successMessage: string,
  ) => {
    setActionJobId(jobId);
    setError("");
    try {
      await action();
      setNotice(successMessage);
      await refreshJobs();
    } catch (actionError: any) {
      setError(actionError?.message || "操作失败，请稍后重试。");
    } finally {
      setActionJobId("");
    }
  };

  const handleDelete = async (job: CronJobSpec) => {
    if (!window.confirm(`确认删除定时任务“${job.name}”吗？`)) {
      return;
    }
    await runJobAction(job.id, () => cronJobsApi.deleteCronJob(job.id), `已删除任务“${job.name}”。`);
  };

  const handleToggleSchedule = async (record: JobRecord) => {
    const { job, state } = record;

    if (job.enabled === false) {
      const payload = { ...job, enabled: true };
      await runJobAction(job.id, () => cronJobsApi.replaceCronJob(job.id, payload), `已启用任务“${job.name}”。`);
      return;
    }

    if (!state.next_run_at) {
      await runJobAction(job.id, () => cronJobsApi.resumeCronJob(job.id), `已恢复任务“${job.name}”。`);
      return;
    }

    await runJobAction(job.id, () => cronJobsApi.pauseCronJob(job.id), `已暂停任务“${job.name}”。`);
  };

  return (
    <div className="cron-jobs-page">
      <div className="portal-model-page-header">
        <div className="portal-model-page-title">
          定时任务 <small>任务调度中心</small>
        </div>
        <div className="portal-model-page-actions">
          <button type="button" className="portal-model-btn" onClick={openCreateModal}>
            <i className="fas fa-plus" />
            新增任务
          </button>
          <button
            type="button"
            className="portal-model-btn"
            onClick={() => void refreshJobs()}
            disabled={loading}
          >
            <i className={`fas ${loading ? "fa-spinner fa-spin" : "fa-rotate-right"}`} />
            刷新
          </button>
        </div>
      </div>

      <div className="cron-jobs-content">
        <div className="cron-jobs-stats">
          <article className="cron-jobs-stat-card">
            <span>任务总数</span>
            <strong>{stats.total}</strong>
          </article>
          <article className="cron-jobs-stat-card accent-green">
            <span>运行中</span>
            <strong>{stats.running}</strong>
          </article>
          <article className="cron-jobs-stat-card accent-amber">
            <span>待首次执行</span>
            <strong>{stats.pending}</strong>
          </article>
          <article className="cron-jobs-stat-card accent-red">
            <span>最近失败</span>
            <strong>{stats.errors}</strong>
          </article>
        </div>

        <div className="cron-jobs-filter-bar">
          {FILTER_OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              className={filter === option.id ? "cron-jobs-filter-chip active" : "cron-jobs-filter-chip"}
              onClick={() => setFilter(option.id)}
            >
              {option.label}
            </button>
          ))}
        </div>

        {notice ? <div className="cron-jobs-notice success">{notice}</div> : null}
        {error ? <div className="cron-jobs-notice error">{error}</div> : null}

        <section className="cron-jobs-table-shell">
          {loading ? (
            <div className="cron-jobs-empty-state">
              <i className="fas fa-spinner fa-spin" />
              <p>正在加载定时任务...</p>
            </div>
          ) : filteredJobs.length ? (
            <div className="cron-jobs-table-wrap">
              <table className="cron-jobs-table">
                <thead>
                  <tr>
                    <th>任务名称</th>
                    <th>调度计划</th>
                    <th>任务类型</th>
                    <th>投递目标</th>
                    <th>状态</th>
                    <th>下次执行</th>
                    <th>上次执行</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredJobs.map((record) => {
                    const { job, state, status } = record;
                    const isBusy = actionJobId === job.id;
                    const scheduleActionLabel =
                      job.enabled === false ? "启用" : !state.next_run_at ? "恢复" : "暂停";

                    return (
                      <tr key={job.id}>
                        <td>
                          <div className="cron-jobs-name-cell">
                            <strong>{job.name}</strong>
                            <span>{job.id}</span>
                          </div>
                        </td>
                        <td>
                          <div className="cron-jobs-schedule-cell">
                            <code>{job.schedule?.cron || "-"}</code>
                            <span>{getCronSummary(job.schedule?.cron || "")}</span>
                          </div>
                        </td>
                        <td>
                          <div className="cron-jobs-type-cell">
                            <span className="cron-jobs-pill">{formatTaskType(job)}</span>
                            <span>{job.dispatch?.mode === "stream" ? "流式投递" : "最终结果投递"}</span>
                          </div>
                        </td>
                        <td>
                          <div className="cron-jobs-target-cell">
                            <span>{formatTarget(job)}</span>
                            <small>{job.schedule?.timezone || "UTC"}</small>
                          </div>
                        </td>
                        <td>
                          <div className="cron-jobs-status-cell">
                            <span className={`cron-jobs-status-badge tone-${status.tone}`}>
                              {status.label}
                            </span>
                            <small>{status.helper}</small>
                          </div>
                        </td>
                        <td>{formatDateTime(state.next_run_at)}</td>
                        <td>{formatDateTime(state.last_run_at)}</td>
                        <td>
                          <div className="cron-jobs-actions">
                            <button
                              type="button"
                              className="cron-jobs-action-btn primary"
                              onClick={() =>
                                void runJobAction(
                                  job.id,
                                  () => cronJobsApi.runCronJob(job.id),
                                  `已触发任务“${job.name}”立即执行。`,
                                )
                              }
                              disabled={isBusy}
                            >
                              立即执行
                            </button>
                            <button
                              type="button"
                              className="cron-jobs-action-btn"
                              onClick={() => void handleToggleSchedule(record)}
                              disabled={isBusy}
                            >
                              {scheduleActionLabel}
                            </button>
                            <button
                              type="button"
                              className="cron-jobs-action-btn"
                              onClick={() => openEditModal(job)}
                              disabled={isBusy}
                            >
                              编辑
                            </button>
                            <button
                              type="button"
                              className="cron-jobs-action-btn danger"
                              onClick={() => void handleDelete(job)}
                              disabled={isBusy}
                            >
                              删除
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="cron-jobs-empty-state">
              <i className="fas fa-clock" />
              <p>{filter === "all" ? "当前还没有定时任务，先创建一个任务。" : "当前筛选条件下没有匹配的任务。"}</p>
            </div>
          )}
        </section>
      </div>

      {isModalOpen ? (
        <div className="cron-jobs-modal-backdrop" onClick={closeModal}>
          <div className="cron-jobs-modal" onClick={(event) => event.stopPropagation()}>
            <div className="cron-jobs-modal-header">
              <div>
                <h4>{editingJob ? "编辑定时任务" : "新增定时任务"}</h4>
                <p>参考 CoPaw 的 CronJobSpec 结构，直接配置调度计划与投递目标。</p>
              </div>
              <button type="button" className="cron-jobs-modal-close" onClick={closeModal}>
                <i className="fas fa-xmark" />
              </button>
            </div>

            <div className="cron-jobs-modal-body">
              <div className="cron-jobs-form-grid two-columns">
                <label>
                  <span>任务名称</span>
                  <input
                    value={formState.name}
                    onChange={(event) => updateForm("name", event.target.value)}
                    placeholder="例如：每日巡检总结"
                  />
                </label>
                <label>
                  <span>时区</span>
                  <input
                    value={formState.timezone}
                    onChange={(event) => updateForm("timezone", event.target.value)}
                    placeholder="Asia/Shanghai"
                  />
                </label>
              </div>

              <div className="cron-jobs-form-grid two-columns compact">
                <label>
                  <span>任务类型</span>
                  <select
                    value={formState.taskType}
                    onChange={(event) => updateForm("taskType", event.target.value as TaskType)}
                  >
                    <option value="agent">Agent 提问</option>
                    <option value="text">固定消息</option>
                  </select>
                </label>
                <label className="cron-jobs-checkbox-field">
                  <span>创建状态</span>
                  <div className="cron-jobs-checkbox-shell">
                    <input
                      type="checkbox"
                      checked={formState.enabled}
                      onChange={(event) => updateForm("enabled", event.target.checked)}
                    />
                    <em>创建后立即生效</em>
                  </div>
                </label>
              </div>

              <div className="cron-jobs-section-card">
                <div className="cron-jobs-section-head">
                  <h5>调度计划</h5>
                  <span>
                    {serializeCron({
                      type: formState.cronType,
                      hour: formState.hour,
                      minute: formState.minute,
                      daysOfWeek: formState.daysOfWeek,
                      rawCron: formState.customCron,
                    })}
                  </span>
                </div>

                <div className="cron-jobs-form-grid two-columns compact">
                  <label>
                    <span>调度类型</span>
                    <select
                      value={formState.cronType}
                      onChange={(event) => updateForm("cronType", event.target.value as CronType)}
                    >
                      <option value="hourly">每小时</option>
                      <option value="daily">每天</option>
                      <option value="weekly">每周</option>
                      <option value="custom">自定义</option>
                    </select>
                  </label>
                  <label>
                    <span>分钟</span>
                    <input
                      type="number"
                      min={0}
                      max={59}
                      value={formState.minute}
                      onChange={(event) => updateForm("minute", Number(event.target.value))}
                      disabled={formState.cronType === "custom"}
                    />
                  </label>
                </div>

                {formState.cronType === "daily" || formState.cronType === "weekly" ? (
                  <div className="cron-jobs-form-grid single-column compact">
                    <label>
                      <span>小时</span>
                      <input
                        type="number"
                        min={0}
                        max={23}
                        value={formState.hour}
                        onChange={(event) => updateForm("hour", Number(event.target.value))}
                      />
                    </label>
                  </div>
                ) : null}

                {formState.cronType === "weekly" ? (
                  <div className="cron-jobs-week-grid">
                    {ORDERED_DAYS.map((day) => {
                      const active = formState.daysOfWeek.includes(day);
                      return (
                        <button
                          key={day}
                          type="button"
                          className={active ? "cron-jobs-week-btn active" : "cron-jobs-week-btn"}
                          onClick={() =>
                            updateForm(
                              "daysOfWeek",
                              active
                                ? formState.daysOfWeek.filter((item) => item !== day)
                                : [...formState.daysOfWeek, day],
                            )
                          }
                        >
                          {DAY_LABELS[day]}
                        </button>
                      );
                    })}
                  </div>
                ) : null}

                {formState.cronType === "custom" ? (
                  <label className="cron-jobs-form-grid single-column compact">
                    <span>Cron 表达式</span>
                    <input
                      value={formState.customCron}
                      onChange={(event) => updateForm("customCron", event.target.value)}
                      placeholder="例如：0 9 * * 1-5"
                    />
                  </label>
                ) : null}
              </div>

              <div className="cron-jobs-section-card">
                <div className="cron-jobs-section-head">
                  <h5>投递目标</h5>
                  <span>与 CoPaw dispatch 字段保持一致</span>
                </div>

                <div className="cron-jobs-form-grid two-columns">
                  <label>
                    <span>通道</span>
                    <input
                      value={formState.channel}
                      onChange={(event) => updateForm("channel", event.target.value)}
                      placeholder="console / dingtalk / discord"
                    />
                  </label>
                  <label>
                    <span>发送模式</span>
                    <select
                      value={formState.mode}
                      onChange={(event) => updateForm("mode", event.target.value as DispatchMode)}
                    >
                      <option value="final">仅最终结果</option>
                      <option value="stream">流式结果</option>
                    </select>
                  </label>
                </div>

                <div className="cron-jobs-form-grid two-columns">
                  <label>
                    <span>目标 user_id</span>
                    <input
                      value={formState.targetUser}
                      onChange={(event) => updateForm("targetUser", event.target.value)}
                      placeholder="例如：cron"
                    />
                  </label>
                  <label>
                    <span>目标 session_id</span>
                    <input
                      value={formState.targetSession}
                      onChange={(event) => updateForm("targetSession", event.target.value)}
                      placeholder="例如：portal-cron"
                    />
                  </label>
                </div>
              </div>

              <label className="cron-jobs-form-grid single-column">
                <span>{formState.taskType === "text" ? "固定消息内容" : "发送给 Agent 的问题"}</span>
                <textarea
                  rows={5}
                  value={formState.content}
                  onChange={(event) => updateForm("content", event.target.value)}
                  placeholder={
                    formState.taskType === "text"
                      ? "请输入任务执行时要发送的文本"
                      : "请输入要定时发送给 Agent 的问题"
                  }
                />
              </label>

              <div className="cron-jobs-section-card">
                <div className="cron-jobs-section-head">
                  <h5>运行参数</h5>
                  <span>对应 runtime 字段</span>
                </div>
                <div className="cron-jobs-form-grid three-columns compact">
                  <label>
                    <span>最大并发</span>
                    <input
                      type="number"
                      min={1}
                      value={formState.maxConcurrency}
                      onChange={(event) => updateForm("maxConcurrency", Number(event.target.value))}
                    />
                  </label>
                  <label>
                    <span>超时秒数</span>
                    <input
                      type="number"
                      min={1}
                      value={formState.timeoutSeconds}
                      onChange={(event) => updateForm("timeoutSeconds", Number(event.target.value))}
                    />
                  </label>
                  <label>
                    <span>补偿窗口</span>
                    <input
                      type="number"
                      min={0}
                      value={formState.misfireGraceSeconds}
                      onChange={(event) => updateForm("misfireGraceSeconds", Number(event.target.value))}
                    />
                  </label>
                </div>
              </div>

              {formError ? <div className="cron-jobs-form-error">{formError}</div> : null}
            </div>

            <div className="cron-jobs-modal-footer">
              <button type="button" className="cron-jobs-footer-btn" onClick={closeModal} disabled={submitting}>
                取消
              </button>
              <button
                type="button"
                className="cron-jobs-footer-btn primary"
                onClick={() => void handleSubmit()}
                disabled={submitting}
              >
                <i className={`fas ${submitting ? "fa-spinner fa-spin" : "fa-floppy-disk"}`} />
                {editingJob ? "保存修改" : "创建任务"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
