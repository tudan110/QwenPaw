import {
  Component,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import {
  digitalEmployees,
  employeeResults,
  employeeWorkflows,
  executionHistory,
  getEmployeeById,
} from "../data/portalData";
import {
  createConversationSession,
  loadConversationStore,
  saveConversationStore,
} from "../lib/conversationStore";
import { deleteChat, listChats, updateChat } from "../api/copawChat";
import DigitalEmployeeAvatar from "../components/DigitalEmployeeAvatar";
import {
  AlarmWorkorderBoard,
  ChatMessageItem,
} from "./digital-employee/components";
import {
  AdvancedModelEntry,
  ChatModelSelector,
  ModelConfigModal,
} from "./digital-employee/modelControls";
import { CronJobsPanel } from "./digital-employee/cronJobsPanel";
import { CliTerminalPanel } from "./digital-employee/cliTerminalPanel";
import { InspirationPanel } from "./digital-employee/inspirationPanel";
import { McpPanel } from "./digital-employee/mcpPanel";
import { OverviewPanel } from "./digital-employee/overviewPanel";
import { SkillPoolPanel } from "./digital-employee/skillPoolPanel";
import { TokenUsagePanel } from "./digital-employee/tokenUsagePanel";
import { OpsExpertPanel } from "./digital-employee/opsExpertPanel";
import {
  ALARM_WORKORDER_ENTRY,
  buildPortalHomePath,
  buildPortalSectionPath,
  buildEmployeePagePath,
  buildSessionTitle,
  createAgentMessage,
  createAlarmWorkorderMessage,
  createUserMessage,
  createWelcomeMessage,
  normalizeRemoteSessions,
  parsePortalAdvancedPanel,
  parsePortalView,
  type PortalAdvancedPanel,
  type PortalRouteSection,
  type PortalView,
} from "./digital-employee/helpers";
import { useAlarmWorkbench } from "./digital-employee/useAlarmWorkbench";
import { usePortalModels } from "./digital-employee/usePortalModels";
import { useRemoteChatSession } from "./digital-employee/useRemoteChatSession";
import { portalAppTitle } from "../config/portalBranding";
import portalLogo from "../assets/images/portal-logo.png";
import "./digital-employee.css";

const sidebarEmployeePriority = [
  "query",
  "fault",
  "resource",
  "inspection",
  "order",
  "knowledge",
] as const;

const REMOTE_AGENT_IDS: Record<string, string> = {
  fault: "fault",
  query: "query",
  knowledge: "knowledge",
};
const DASHBOARD_CHAT_CHANNEL = "console";

const PORTAL_HOME_AGENT_ID = "default";
const EMPLOYEE_MENTION_ALIASES: Record<string, string[]> = {
  resource: ["资产", "资源", "纳管"],
  fault: ["故障", "告警", "修复"],
  inspection: ["巡检", "巡查", "检查"],
  order: ["工单", "流程", "审批"],
  query: ["数据", "数字", "洞察", "报表"],
  knowledge: ["知识", "知库", "文档"],
};

const PAGE_THEME_STORAGE_KEY = "portal-digital-employee-theme";
const PORTAL_HOME_ID = "portal-home";
const PORTAL_CLOSE_DRAWER_MESSAGE = {
  source: "qwenpaw-portal",
  type: "portal:close-drawer",
  reason: "switch-traditional-view",
} as const;

type DashboardKanbanMode = "work" | "employee";
type DashboardKanbanFilter = "all" | "urgent" | "running";
type DashboardWorkColumnId = "pending" | "running" | "completed" | "closed";

type DashboardWorkCard = {
  id: string;
  ownerEmployeeIds: string[];
  ownerLabel: string;
  ownerColor: string;
  title: string;
  description: string;
  label: string;
  tagBg: string;
  tagColor: string;
  timeText: string;
  progress?: number;
  score?: number;
  isUrgent: boolean;
  isRunning: boolean;
};

type DashboardWorkColumn = {
  id: DashboardWorkColumnId;
  title: string;
  dot: string;
  cards: DashboardWorkCard[];
};

type DashboardEmployeeSnapshot = {
  id: string;
  name: string;
  desc: string;
  color: string;
  runtimeState: "running" | "idle";
  currentJob: string;
  historyCount: number;
  progress: number;
  workStatus: string;
  updatedAt: string;
  urgent: boolean;
};

const DASHBOARD_EMPLOYEE_COLORS: Record<string, string> = {
  resource: "#3b82f6",
  fault: "#ef4444",
  inspection: "#22c55e",
  order: "#f59e0b",
  query: "#8b5cf6",
  knowledge: "#06b6d4",
};

const DASHBOARD_TAG_STYLES = {
  resource: { bg: "rgba(59, 130, 246, 0.15)", color: "#60a5fa" },
  fault: { bg: "rgba(239, 68, 68, 0.15)", color: "#f87171" },
  inspection: { bg: "rgba(34, 197, 94, 0.15)", color: "#4ade80" },
  order: { bg: "rgba(245, 158, 11, 0.15)", color: "#fbbf24" },
  query: { bg: "rgba(139, 92, 246, 0.15)", color: "#a78bfa" },
  knowledge: { bg: "rgba(6, 182, 212, 0.15)", color: "#22d3ee" },
  collaboration: { bg: "rgba(168, 85, 247, 0.14)", color: "#c084fc" },
} as const;

function getDashboardEmployeeColor(employeeId: string) {
  return DASHBOARD_EMPLOYEE_COLORS[employeeId] || "#6366f1";
}

function getDashboardFilterLabels(mode: DashboardKanbanMode) {
  return mode === "employee"
    ? {
        all: "全部",
        urgent: "运行中",
        running: "闲置中",
      }
    : {
        all: "全部",
        urgent: "紧急",
        running: "进行中",
      };
}

function formatDashboardClock(value: Date) {
  return value.toLocaleTimeString("zh-CN", {
    hour12: false,
  });
}

function buildDashboardWorkColumns(): DashboardWorkColumn[] {
  const employee = (employeeId: string) => getEmployeeById(employeeId);
  const employeeName = (employeeId: string) => employee(employeeId)?.name || employeeId;
  const employeeColor = (employeeId: string) => getDashboardEmployeeColor(employeeId);
  const employeeTag = (employeeId: keyof typeof DASHBOARD_TAG_STYLES) =>
    DASHBOARD_TAG_STYLES[employeeId];
  const collaborationTag = DASHBOARD_TAG_STYLES.collaboration;

  return [
    {
      id: "pending",
      title: "待处理",
      dot: "#f59e0b",
      cards: [
        {
          id: "pending-fault-port-down",
          ownerEmployeeIds: ["fault"],
          ownerLabel: employeeName("fault"),
          ownerColor: employeeColor("fault"),
          title: `${employeeName("fault")}核心交换端口 down 待接续`,
          description: "南北向链路告警已聚合，等待继续执行根因定位与恢复策略。",
          label: "故障",
          tagBg: employeeTag("fault").bg,
          tagColor: employeeTag("fault").color,
          timeText: "6分钟前",
          isUrgent: true,
          isRunning: false,
        },
        {
          id: "pending-inspection-baseline",
          ownerEmployeeIds: ["inspection"],
          ownerLabel: employeeName("inspection"),
          ownerColor: employeeColor("inspection"),
          title: `${employeeName("inspection")}夜间基线巡检待执行`,
          description: "核心主机、数据库与中间件的例行健康检查窗口已排入待办。",
          label: "巡检",
          tagBg: employeeTag("inspection").bg,
          tagColor: employeeTag("inspection").color,
          timeText: "20分钟前",
          isUrgent: false,
          isRunning: false,
        },
        {
          id: "pending-knowledge-archive",
          ownerEmployeeIds: ["knowledge"],
          ownerLabel: employeeName("knowledge"),
          ownerColor: employeeColor("knowledge"),
          title: `${employeeName("knowledge")}故障案例归档待同步`,
          description: "上一轮数据库慢查询处置案例待结构化归档并写回知识库。",
          label: "知识",
          tagBg: employeeTag("knowledge").bg,
          tagColor: employeeTag("knowledge").color,
          timeText: "42分钟前",
          isUrgent: false,
          isRunning: false,
        },
      ],
    },
    {
      id: "running",
      title: "进行中",
      dot: "#3b82f6",
      cards: [
        {
          id: "running-resource-discovery",
          ownerEmployeeIds: ["resource"],
          ownerLabel: employeeName("resource"),
          ownerColor: employeeColor("resource"),
          title: `${employeeName("resource")}核心网段纳管扫描中`,
          description: "正在发现新入网设备与服务端口，补全资源模型与纳管标签。",
          label: "纳管",
          tagBg: employeeTag("resource").bg,
          tagColor: employeeTag("resource").color,
          timeText: "进行中",
          progress: 68,
          isUrgent: false,
          isRunning: true,
        },
        {
          id: "running-fault-diagnosis",
          ownerEmployeeIds: ["fault"],
          ownerLabel: employeeName("fault"),
          ownerColor: employeeColor("fault"),
          title: `${employeeName("fault")}端口 down 根因定位中`,
          description: "正在关联接口流量、邻接状态与拓扑路径，输出根因与处置建议。",
          label: "故障",
          tagBg: employeeTag("fault").bg,
          tagColor: employeeTag("fault").color,
          timeText: "紧急",
          progress: 84,
          isUrgent: true,
          isRunning: true,
        },
        {
          id: "running-query-report",
          ownerEmployeeIds: ["query"],
          ownerLabel: employeeName("query"),
          ownerColor: employeeColor("query"),
          title: `${employeeName("query")}设备分布报表生成中`,
          description: "设备类型、区域分布和容量画像已进入聚合与图表输出阶段。",
          label: "报表",
          tagBg: employeeTag("query").bg,
          tagColor: employeeTag("query").color,
          timeText: "进行中",
          progress: 57,
          isUrgent: false,
          isRunning: true,
        },
        {
          id: "running-order-routing",
          ownerEmployeeIds: ["order"],
          ownerLabel: employeeName("order"),
          ownerColor: employeeColor("order"),
          title: `${employeeName("order")}告警派单流转中`,
          description: "正在对接告警入口，将高优先级事件分派到对应数字员工流程。",
          label: "工单",
          tagBg: employeeTag("order").bg,
          tagColor: employeeTag("order").color,
          timeText: "进行中",
          progress: 63,
          isUrgent: false,
          isRunning: true,
        },
        {
          id: "running-collaboration-fault-query",
          ownerEmployeeIds: ["fault", "query"],
          ownerLabel: `${employeeName("fault")} + ${employeeName("query")}`,
          ownerColor: "#8b5cf6",
          title: "故障与数据协同复盘中",
          description: "围绕链路抖动、响应时间与异常分布进行联合分析，输出复盘结论。",
          label: "协同",
          tagBg: collaborationTag.bg,
          tagColor: collaborationTag.color,
          timeText: "进行中",
          progress: 49,
          isUrgent: false,
          isRunning: true,
        },
      ],
    },
    {
      id: "completed",
      title: "已完成",
      dot: "#22c55e",
      cards: [
        {
          id: "completed-query-summary",
          ownerEmployeeIds: ["query"],
          ownerLabel: employeeName("query"),
          ownerColor: employeeColor("query"),
          title: `${employeeName("query")}容量趋势分析已完成`,
          description: "核心业务链路的容量曲线、峰值时段与增长趋势已归档。",
          label: "分析",
          tagBg: employeeTag("query").bg,
          tagColor: employeeTag("query").color,
          timeText: "1小时前",
          isUrgent: false,
          isRunning: false,
        },
        {
          id: "completed-resource-onboard",
          ownerEmployeeIds: ["resource"],
          ownerLabel: employeeName("resource"),
          ownerColor: employeeColor("resource"),
          title: `${employeeName("resource")}新增设备纳管已完成`,
          description: "新接入交换机与服务器已完成识别、分类与资源建模。",
          label: "纳管",
          tagBg: employeeTag("resource").bg,
          tagColor: employeeTag("resource").color,
          timeText: "2小时前",
          isUrgent: false,
          isRunning: false,
        },
        {
          id: "completed-order-closure",
          ownerEmployeeIds: ["order"],
          ownerLabel: employeeName("order"),
          ownerColor: employeeColor("order"),
          title: `${employeeName("order")}告警闭环记录已输出`,
          description: "上一轮自动派单、确认和关闭流程已生成处理摘要。",
          label: "流程",
          tagBg: employeeTag("order").bg,
          tagColor: employeeTag("order").color,
          timeText: "今天",
          isUrgent: false,
          isRunning: false,
        },
      ],
    },
    {
      id: "closed",
      title: "已关闭",
      dot: "#64748b",
      cards: [
        {
          id: "closed-knowledge-retro",
          ownerEmployeeIds: ["knowledge"],
          ownerLabel: employeeName("knowledge"),
          ownerColor: employeeColor("knowledge"),
          title: `${employeeName("knowledge")}历史方案归档已关闭`,
          description: "重复知识条目合并完成，旧版本方案已下线归档。",
          label: "知识",
          tagBg: employeeTag("knowledge").bg,
          tagColor: employeeTag("knowledge").color,
          timeText: "昨天",
          score: 4.8,
          isUrgent: false,
          isRunning: false,
        },
        {
          id: "closed-fault-false-positive",
          ownerEmployeeIds: ["fault"],
          ownerLabel: employeeName("fault"),
          ownerColor: employeeColor("fault"),
          title: `${employeeName("fault")}误报告警复盘已关闭`,
          description: "阈值误触发问题已定位，处置记录已完成回收与复盘闭环。",
          label: "复盘",
          tagBg: "rgba(100, 116, 139, 0.15)",
          tagColor: "#94a3b8",
          timeText: "2天前",
          score: 4.6,
          isUrgent: false,
          isRunning: false,
        },
      ],
    },
  ];
}

function buildDashboardEmployeeSnapshots(
  historyCounts: Record<string, number>,
): DashboardEmployeeSnapshot[] {
  const templates: Record<
    string,
    Omit<DashboardEmployeeSnapshot, "id" | "name" | "desc" | "color" | "historyCount" | "urgent">
  > = {
    resource: {
      runtimeState: "running",
      currentJob: `${getEmployeeById("resource")?.name || "资产管理员"}核心网段纳管扫描中`,
      progress: 68,
      workStatus: "纳管扫描中",
      updatedAt: "2分钟前",
    },
    fault: {
      runtimeState: "running",
      currentJob: `${getEmployeeById("fault")?.name || "故障处置员"}端口 down 根因定位中`,
      progress: 84,
      workStatus: "根因定位中",
      updatedAt: "刚刚",
    },
    inspection: {
      runtimeState: "idle",
      currentJob: `${getEmployeeById("inspection")?.name || "巡检专员"}夜间健康巡检待执行`,
      progress: 12,
      workStatus: "待执行",
      updatedAt: "15分钟前",
    },
    order: {
      runtimeState: "running",
      currentJob: `${getEmployeeById("order")?.name || "工单调度员"}告警派单流转中`,
      progress: 63,
      workStatus: "流转处理中",
      updatedAt: "4分钟前",
    },
    query: {
      runtimeState: "running",
      currentJob: `${getEmployeeById("query")?.name || "数据分析员"}设备分布报表生成中`,
      progress: 57,
      workStatus: "报表生成中",
      updatedAt: "7分钟前",
    },
    knowledge: {
      runtimeState: "running",
      currentJob: `${getEmployeeById("knowledge")?.name || "知识专员"}故障案例归档中`,
      progress: 46,
      workStatus: "知识整理中",
      updatedAt: "9分钟前",
    },
  };

  return digitalEmployees.map((employee) => {
    const template = templates[employee.id];
    const runtimeState =
      employee.status === "running" ? "running" : template?.runtimeState || "idle";
    return {
      id: employee.id,
      name: employee.name,
      desc: employee.desc,
      color: getDashboardEmployeeColor(employee.id),
      runtimeState,
      currentJob: template?.currentJob || `${employee.name}任务处理中`,
      historyCount: historyCounts[employee.id] || 0,
      progress: template?.progress ?? 0,
      workStatus: template?.workStatus || (runtimeState === "running" ? "运行中" : "待命中"),
      updatedAt: template?.updatedAt || "刚刚",
      urgent: employee.urgent,
    };
  });
}

const PORTAL_HOME_EMPLOYEE = {
  id: PORTAL_HOME_ID,
  name: "数字员工协同入口",
  desc: "统一接入对话，可通过 @ 标签切换到具体数字员工",
  icon: "fa-comments",
  tasks: 0,
  success: "100%",
  status: "running",
  urgent: false,
  gradient: "linear-gradient(135deg, #1d4ed8, #0f172a)",
  capabilities: [
    "@mention 路由",
    "对话协同",
    "跨员工切换",
    "入口导航",
  ],
  quickCommands: [
    "当前有哪些设备？",
    "数据库响应很慢，请帮我定位",
    "Oracle 死锁怎么处理？",
    "帮我判断这个问题应该交给哪个数字员工",
  ],
  welcome: "",
} as const;

type PendingPortalDispatch = {
  token: string;
  targetEmployeeId: string;
  content: string;
  visibleContent: string;
};

type PortalLocationState = {
  pendingPortalDispatch?: PendingPortalDispatch;
  openHistoryForEmployeeId?: string;
  openSession?: {
    employeeId: string;
    sessionId: string;
  };
};

type PortalOpsAlertLevel = "critical" | "urgent" | "warning" | "info";

type PortalOpsAlert = {
  id: string;
  employeeId: string;
  level: PortalOpsAlertLevel;
  message: string;
  timeLabel: string;
  routeEntry?: string | null;
  dispatchContent?: string;
  visibleContent?: string;
};

const PORTAL_ALERT_LEVEL_LABELS: Record<PortalOpsAlertLevel, string> = {
  critical: "紧急",
  urgent: "严重",
  warning: "警告",
  info: "通知",
};

const PORTAL_ALERT_LEVEL_COLORS: Record<PortalOpsAlertLevel, string> = {
  critical: "#ef4444",
  urgent: "#f97316",
  warning: "#f59e0b",
  info: "#22d3ee",
};

const PORTAL_OPS_ALERTS_INITIAL: PortalOpsAlert[] = [
  {
    id: "alert-fault-payment-pool",
    employeeId: "fault",
    level: "critical",
    message: "支付服务连接池耗尽，故障处置员待执行自动修复。",
    timeLabel: "2分钟前",
    routeEntry: ALARM_WORKORDER_ENTRY,
  },
  {
    id: "alert-fault-slow-sql",
    employeeId: "fault",
    level: "urgent",
    message: "核心交易库慢 SQL 告警持续 12 分钟，请进入工单处置。",
    timeLabel: "5分钟前",
    routeEntry: ALARM_WORKORDER_ENTRY,
  },
  {
    id: "alert-query-error-rate",
    employeeId: "query",
    level: "warning",
    message: "API 错误率升至 4.2%，请生成趋势分析并定位异常时间段。",
    timeLabel: "8分钟前",
    dispatchContent: "请分析告警：API 错误率升至 4.2%，按时间维度给出趋势、异常波峰和可能原因。",
  },
  {
    id: "alert-knowledge-kafka",
    employeeId: "knowledge",
    level: "warning",
    message: "Kafka 消费堆积告警触发，请检索相似案例与处置建议。",
    timeLabel: "12分钟前",
    dispatchContent: "请检索 Kafka 消费堆积告警的相似故障案例，并给出处置建议和排查顺序。",
  },
  {
    id: "alert-resource-discovery",
    employeeId: "resource",
    level: "info",
    message: "发现一批新增云主机，建议资产管理员执行自动纳管。",
    timeLabel: "18分钟前",
    dispatchContent: "收到新增云主机告警，请帮我梳理待纳管资源，并给出纳管建议。",
  },
];

type SessionRecord = {
  id: string;
  title: string;
  createdAt?: string;
  updatedAt?: string;
  messages?: any[];
  sessionId?: string;
  status?: string;
  meta?: Record<string, unknown>;
  detail?: string;
  tag?: string;
};

type ConversationStoreState = Record<string, SessionRecord[]>;
type ExecutionRecord = {
  id: string | number;
  time?: string;
  title?: string;
  detail?: string;
  agent?: string;
  agentIcon?: string;
  status?: string;
};

function loadPageTheme(): "light" | "dark" {
  if (typeof window === "undefined") {
    return "light";
  }

  try {
    return window.localStorage.getItem(PAGE_THEME_STORAGE_KEY) === "dark" ? "dark" : "light";
  } catch (error) {
    console.error("Failed to load persisted page theme:", error);
    return "light";
  }
}

function persistPageTheme(theme: "light" | "dark"): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(PAGE_THEME_STORAGE_KEY, theme);
  } catch (error) {
    console.error("Failed to persist page theme:", error);
  }
}

function ensureSessionRecords(value: unknown): SessionRecord[] {
  return Array.isArray(value) ? (value as SessionRecord[]) : [];
}

function ensureObjectArray<T = Record<string, unknown>>(value: unknown): T[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (item): item is T => typeof item === "object" && item !== null,
  );
}

function ensureStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string");
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function extractMentionTarget(rawContent: string) {
  const normalizedContent = String(rawContent || "").trim();
  if (!normalizedContent.includes("@")) {
    return {
      employee: null,
      cleanContent: normalizedContent,
      visibleContent: normalizedContent,
    };
  }

  const employeeNames = [...digitalEmployees]
    .sort((left, right) => right.name.length - left.name.length)
    .map((employee) => escapeRegExp(employee.name))
    .join("|");

  if (!employeeNames) {
    return {
      employee: null,
      cleanContent: normalizedContent,
      visibleContent: normalizedContent,
    };
  }

  const mentionPattern = new RegExp(`@\\s*(${employeeNames})`);
  const matched = normalizedContent.match(mentionPattern);
  if (!matched?.[1]) {
    return {
      employee: null,
      cleanContent: normalizedContent,
      visibleContent: normalizedContent,
    };
  }

  const employee = digitalEmployees.find((item) => item.name === matched[1]) || null;
  if (!employee) {
    return {
      employee: null,
      cleanContent: normalizedContent,
      visibleContent: normalizedContent,
    };
  }

  const cleanContent = normalizedContent
    .replace(mentionPattern, "")
    .replace(/^[\s,，:：;；-]+/, "")
    .trim();

  return {
    employee,
    cleanContent,
    visibleContent: normalizedContent,
  };
}

function resolveEmployeeAgentId(employeeId: string) {
  return REMOTE_AGENT_IDS[employeeId] || employeeId;
}

function buildMentionCollaborationPrompt({
  currentEmployee,
  currentAgentId,
  targetEmployee,
  userRequest,
}: {
  currentEmployee: any;
  currentAgentId: string;
  targetEmployee: any;
  userRequest: string;
}) {
  const targetAgentId = resolveEmployeeAgentId(String(targetEmployee?.id || ""));
  const normalizedRequest = String(userRequest || "").trim();

  return [
    `你当前是数字员工「${currentEmployee?.name || currentAgentId}」。`,
    `用户在当前会话中 @ 了另一位数字员工「${targetEmployee?.name || targetAgentId}」。`,
    "请不要要求用户切换页面，也不要把本次请求交回前端路由处理。",
    "请直接使用你已启用的内置技能 Multi-Agent Collaboration（multi_agent_collaboration），在当前会话中发起智能体协同并整合结果后回复用户。",
    "给目标智能体的协同请求正文请直接概括任务本身，不要重复写 [Agent ... requesting]，也不要以 User explicitly asked... 这类泛化说明开头。",
    `当前智能体（from-agent）：${currentAgentId}`,
    `目标智能体（to-agent）：${targetAgentId}`,
    normalizedRequest
      ? `用户希望协同处理的内容：${normalizedRequest}`
      : `用户目前只 @ 了「${targetEmployee?.name || targetAgentId}」，请先确认需要对方协助的具体问题，再决定如何发起协同。`,
  ].join("\n");
}

function extractMentionQuery(value: string, cursorPosition: number | null) {
  const safeCursor = cursorPosition ?? value.length;
  const beforeCursor = String(value || "").slice(0, safeCursor);
  const matched = beforeCursor.match(/(^|\s)@([^\s@]*)$/);
  if (!matched) {
    return null;
  }

  const query = matched[2] || "";
  return {
    query,
    start: safeCursor - query.length - 1,
    end: safeCursor,
  };
}

function scoreMentionCandidate(employee: (typeof digitalEmployees)[number], query: string) {
  const normalizedQuery = query.trim();
  if (!normalizedQuery) {
    return 1;
  }

  const sources = [
    employee.name,
    employee.desc,
    ...(EMPLOYEE_MENTION_ALIASES[employee.id] || []),
  ].filter(Boolean);

  let bestScore = 0;
  for (const source of sources) {
    if (source === normalizedQuery) {
      bestScore = Math.max(bestScore, 100);
      continue;
    }
    if (source.startsWith(normalizedQuery)) {
      bestScore = Math.max(bestScore, 80);
      continue;
    }
    if (source.includes(normalizedQuery)) {
      bestScore = Math.max(bestScore, 60);
      continue;
    }

    const overlap = [...normalizedQuery].filter((char) => source.includes(char)).length;
    if (overlap > 0) {
      bestScore = Math.max(bestScore, overlap * 10);
    }
  }

  return bestScore;
}

function buildPortalAssistantReply(content: string) {
  const normalized = String(content || "").trim();
  const suggestions = [
    { employee: "数据分析员", keywords: ["设备", "指标", "报表", "趋势", "性能", "查询", "可用性"] },
    { employee: "故障处置员", keywords: ["故障", "异常", "超时", "中断", "恢复", "慢", "报警", "告警"] },
    { employee: "资产管理员", keywords: ["资产", "纳管", "扫描", "发现", "拓扑", "资源"] },
    { employee: "巡检专员", keywords: ["巡检", "健康", "检查", "日报", "周报"] },
    { employee: "知识专员", keywords: ["怎么", "最佳实践", "方案", "知识", "原理"] },
    { employee: "工单调度员", keywords: ["工单", "审批", "转派", "流程"] },
  ];

  const recommended = suggestions
    .filter((item) => item.keywords.some((keyword) => normalized.includes(keyword)))
    .map((item) => item.employee)
    .slice(0, 2);

  const recommendationLine = recommended.length
    ? `更适合接手的数字员工：${recommended.map((name) => `\`@${name}\``).join("、")}。`
    : "如果您已经知道处理角色，可以直接在问题前加上 `@数字员工名`。";

  return [
    "我已经收到您的问题。",
    "",
    recommendationLine,
    "",
    "当前支持的常用协同方式：",
    "- 直接点击上方数字员工标签，进入该员工专属对话",
    "- 输入 `@数字员工名 + 需求`，我会自动切换并执行对应员工逻辑",
    "",
    "可直接复制这些示例继续：",
    "- `当前有哪些设备？`",
    "- `数据库响应很慢，请帮我定位`",
    "- `Oracle 死锁怎么处理？`",
  ].join("\n");
}

class DigitalEmployeeErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    console.error("DigitalEmployeePage render failed:", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="portal-digital-employee">
          <div className="app-container">
            <div className="main-content">
              <div className="history-empty" style={{ minHeight: 360 }}>
                <i className="fas fa-triangle-exclamation" />
                <p>数字员工页面渲染失败，请刷新后重试。</p>
              </div>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function DigitalEmployeePage({
  forcedSection,
}: {
  forcedSection?: PortalRouteSection;
}) {
  const { employeeId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const locationState = (location.state || null) as PortalLocationState | null;
  const routeSearchParams = useMemo(
    () => new URLSearchParams(location.search),
    [location.search],
  );
  const selectedEmployee = useMemo(() => {
    const routeEmployeeId = employeeId || routeSearchParams.get("employee");
    if (!routeEmployeeId) {
      return null;
    }
    return digitalEmployees.find((item) => item.id === routeEmployeeId) || null;
  }, [employeeId, routeSearchParams]);
  const portalHomeEmployee = useMemo(() => ({ ...PORTAL_HOME_EMPLOYEE }), []);
  const currentEmployee = selectedEmployee || portalHomeEmployee;
  const routeSection = forcedSection || null;
  const remoteAgentId = selectedEmployee
    ? (REMOTE_AGENT_IDS[selectedEmployee.id] || null)
    : PORTAL_HOME_AGENT_ID;
  const isRemoteEmployee = Boolean(remoteAgentId);
  const currentEntry = routeSearchParams.get("entry");
  const currentView = parsePortalView(routeSection ?? routeSearchParams.get("view"));
  const activeAdvancedPanel = parsePortalAdvancedPanel(
    routeSection ?? routeSearchParams.get("panel"),
  );
  const isPortalHome = !selectedEmployee;
  const isPortalHomeChat = isPortalHome && currentView === "chat" && !activeAdvancedPanel;
  const isAlarmWorkbenchMode = Boolean(
    selectedEmployee?.id === "fault" && currentEntry === ALARM_WORKORDER_ENTRY,
  );

  const [employeeDropdownOpen, setEmployeeDropdownOpen] = useState(false);
  const [inputMessage, setInputMessage] = useState("");
  const [inputCursor, setInputCursor] = useState<number | null>(null);
  const [mentionActiveIndex, setMentionActiveIndex] = useState(0);
  const [messages, setMessages] = useState<any[]>([]);
  const [conversationStore, setConversationStore] = useState<ConversationStoreState>(
    () => loadConversationStore() as ConversationStoreState,
  );
  const [executionVisible, setExecutionVisible] = useState(false);
  const [executionTitle, setExecutionTitle] = useState("执行历史");
  const [executionList, setExecutionList] = useState(executionHistory);
  const [pageTheme, setPageTheme] = useState<"light" | "dark">(loadPageTheme);
  const [opsAlerts, setOpsAlerts] = useState<PortalOpsAlert[]>(PORTAL_OPS_ALERTS_INITIAL);
  const [alertPopupOpen, setAlertPopupOpen] = useState(false);
  const [kanbanMode, setKanbanMode] = useState<DashboardKanbanMode>("employee");
  const [kanbanFilter, setKanbanFilter] = useState<DashboardKanbanFilter>("all");
  const themeToggleIcon: ReactNode = pageTheme === "light" ? (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  ) : (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  );
  const alertBellIcon: ReactNode = (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </svg>
  );
  const [dashboardRemoteHistoryCounts, setDashboardRemoteHistoryCounts] = useState<Record<string, number>>({});
  const [dashboardRemoteSessionsMap, setDashboardRemoteSessionsMap] = useState<Record<string, SessionRecord[]>>({});
  const [dashboardClock, setDashboardClock] = useState(() => formatDashboardClock(new Date()));
  const [dashboardHistoryVisible, setDashboardHistoryVisible] = useState(false);
  const [dashboardHistoryEmployeeId, setDashboardHistoryEmployeeId] = useState("");
  const [dashboardHistorySessions, setDashboardHistorySessions] = useState<SessionRecord[]>([]);
  const [dashboardHistoryLoading, setDashboardHistoryLoading] = useState(false);
  const [dashboardHistoryError, setDashboardHistoryError] = useState("");
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const handledPendingDispatchRef = useRef("");
  const handledDashboardSessionOpenRef = useRef("");
  const chatInputRef = useRef<HTMLInputElement | null>(null);
  const homeComposerRef = useRef<HTMLTextAreaElement | null>(null);
  const employeeDropdownRef = useRef<HTMLDivElement | null>(null);
  const alertPopupRef = useRef<HTMLDivElement | null>(null);
  const activeAlertTriggerRef = useRef<HTMLButtonElement | null>(null);
  const [historyEditingId, setHistoryEditingId] = useState("");
  const [historyDraftTitle, setHistoryDraftTitle] = useState("");
  const [historyActionSessionId, setHistoryActionSessionId] = useState("");
  const [historyActionError, setHistoryActionError] = useState("");
  const [alertPopupPosition, setAlertPopupPosition] = useState<{ top: number; left: number } | null>(null);

  const {
    currentSessionId,
    setCurrentSessionId,
    currentChatId,
    currentChatStatus,
    historyVisible,
    setHistoryVisible,
    historyLoading,
    historyError,
    remoteSessions,
    isCreatingChat,
    isStreaming,
    activeAssistantMessageIdRef,
    handleRemoteSendMessage,
    stopActiveStream,
    refreshRemoteSessions,
    handleOpenHistory,
    handleSelectRemoteHistory,
    resetRemoteState,
  } = useRemoteChatSession({
    currentEmployee,
    isRemoteEmployee,
    remoteAgentId,
    setMessages,
  });

  const {
    alarmWorkorders,
    alarmWorkordersLoading,
    alarmWorkordersError,
    ticketActionNotice,
    faultDiagnosisBusy,
    pendingDisposalAction,
    isSubmittingDisposalAction,
    loadAlarmWorkorders,
    handleAlarmWorkbenchTicketAction,
    handleAlarmDisposalOperationRequest,
    handleCancelDisposalAction,
    handleConfirmDisposalAction,
    resetAlarmWorkbench,
  } = useAlarmWorkbench({
    currentEmployee,
    isAlarmWorkbenchMode,
    currentSessionId,
    handleRemoteSendMessage,
    messages,
    setMessages,
  });

  const modelAgentId = remoteAgentId || "default";
  const {
    displayProviders,
    eligibleProviders,
    activeProviderId,
    activeProviderName,
    activeModelId,
    activeModelLabel,
    loading: modelsLoading,
    switching: modelsSwitching,
    submitting: modelsSubmitting,
    notice: modelNotice,
    fetchModelState,
    handleSelectModel,
    handleSaveProvider,
    handleAddModel,
    handleDeleteProvider,
    handleRevokeProviderAuth,
    handleApplyBuiltinApiKey,
    handleRemoveModel,
    handleConfigureModel,
    handleTestProvider,
    handleTestModel,
    handleProbeMultimodal,
    handleDiscoverModels,
  } = usePortalModels({
    agentId: modelAgentId,
    enabled: Boolean(currentEmployee),
  });

  const navigateToEmployeePage = useCallback((
    employee: any,
    options: {
      entry?: string | null;
      view?: PortalView;
      panel?: PortalAdvancedPanel | null;
      replace?: boolean;
      state?: PortalLocationState;
    } = {},
  ) => {
    navigate(
      buildEmployeePagePath(employee, {
        entry: options.entry,
        view: options.view,
        panel: options.panel,
      }),
      options.replace || options.state
        ? {
            ...(options.replace ? { replace: true } : {}),
            ...(options.state ? { state: options.state } : {}),
          }
        : undefined,
    );
  }, [navigate]);

  const navigateToPortalHome = useCallback((
    options: {
      entry?: string | null;
      view?: PortalView;
      panel?: PortalAdvancedPanel | null;
      replace?: boolean;
      state?: PortalLocationState;
    } = {},
  ) => {
    navigate(
      buildPortalHomePath({
        entry: options.entry,
        view: options.view,
        panel: options.panel,
      }),
      options.replace || options.state ? { replace: Boolean(options.replace), state: options.state } : undefined,
    );
  }, [navigate]);

  const handleSwitchTraditionalView = useCallback(() => {
    if (window.parent !== window) {
      window.parent.postMessage(PORTAL_CLOSE_DRAWER_MESSAGE, "*");
    }
  }, []);

  const updateCurrentEmployeeRoute = useCallback((
    options: {
      entry?: string | null;
      view?: PortalView;
      panel?: PortalAdvancedPanel | null;
      replace?: boolean;
    } = {},
  ) => {
    const nextEntry = options.entry ?? currentEntry;
    const nextView = options.view ?? currentView;
    const nextPanel =
      options.panel === undefined ? activeAdvancedPanel : options.panel;

    if (selectedEmployee) {
      navigateToEmployeePage(selectedEmployee, {
        entry: nextEntry,
        view: nextView,
        panel: nextPanel,
        replace: options.replace,
      });
      return;
    }

    navigateToPortalHome({
      entry: nextEntry,
      view: nextView,
      panel: nextPanel,
      replace: options.replace,
    });
  }, [
    activeAdvancedPanel,
    currentEntry,
    currentView,
    navigateToEmployeePage,
    navigateToPortalHome,
    selectedEmployee,
  ]);

  const openModelConfig = () => {
    updateCurrentEmployeeRoute({
      panel: "model-config",
    });
  };

  const openSkillPool = useCallback(() => {
    navigate(buildPortalSectionPath("skill-pool"));
  }, [navigate]);

  const openInspiration = useCallback(() => {
    navigate(buildPortalSectionPath("inspiration"));
  }, [navigate]);

  const openCli = useCallback(() => {
    navigate(
      buildPortalSectionPath("cli", {
        employeeId: selectedEmployee?.id || null,
      }),
    );
  }, [navigate, selectedEmployee?.id]);

  const switchMcpEmployee = useCallback((employeeId: string | null) => {
    navigate(buildPortalSectionPath("mcp", { employeeId }));
  }, [navigate]);

  const openEmployeeChat = useCallback((targetEmployeeId: string) => {
    const employee = digitalEmployees.find((item) => item.id === targetEmployeeId);
    if (!employee) {
      return;
    }
    navigateToEmployeePage(employee, {
      entry: null,
      view: "chat",
      panel: null,
    });
  }, [navigateToEmployeePage]);

  useEffect(() => {
    if (!currentEmployee) {
      return;
    }

    if (employeeId && !selectedEmployee) {
      navigate("/", { replace: true });
      return;
    }

    if (routeSearchParams.has("view") || routeSearchParams.has("panel")) {
      updateCurrentEmployeeRoute({
        entry: currentEntry,
        view: currentView,
        panel: activeAdvancedPanel,
        replace: true,
      });
    }
  }, [
    activeAdvancedPanel,
    currentEmployee,
    currentEntry,
    currentView,
    employeeId,
    navigate,
    routeSearchParams,
    routeSection,
    selectedEmployee,
    updateCurrentEmployeeRoute,
  ]);

  useEffect(() => {
    if (!currentEmployee) {
      return;
    }

    setInputMessage("");
    setExecutionVisible(false);
    resetAlarmWorkbench();

    if (isAlarmWorkbenchMode) {
      resetRemoteState({
        initialMessages: [
          createAlarmWorkorderMessage(currentEmployee, {
            content: "告警已触发，我正在为您查询待处置工单...",
            workorders: [],
            workordersLoading: true,
            workordersError: "",
          }),
        ],
      });
      return;
    }

    if (!isRemoteEmployee) {
      resetRemoteState();
      const initialMessages = isPortalHome ? [] : [createWelcomeMessage(currentEmployee)];
      const nextSession = isPortalHome
        ? null
        : createConversationSession(currentEmployee, initialMessages);

      if (nextSession) {
        setConversationStore((prevStore) => {
          const previousSessions = ensureSessionRecords(prevStore[currentEmployee.id]);
          const nextStore: ConversationStoreState = {
            ...prevStore,
            [currentEmployee.id]: [
              nextSession as SessionRecord,
              ...previousSessions,
            ],
          };
          saveConversationStore(nextStore);
          return nextStore;
        });
      }

      setCurrentSessionId(nextSession?.id || "");
      setMessages(initialMessages);
      return;
    }

    resetRemoteState({
      initialMessages: isPortalHome ? [] : [createWelcomeMessage(currentEmployee)],
    });
  }, [
    currentEmployee,
    isPortalHome,
    isAlarmWorkbenchMode,
    isRemoteEmployee,
    resetAlarmWorkbench,
    resetRemoteState,
    setCurrentSessionId,
  ]);

  useEffect(() => {
    const timerId = window.requestAnimationFrame(() => {
      messagesEndRef.current?.scrollIntoView({
        behavior: isStreaming ? "auto" : "smooth",
        block: "end",
      });
    });

    return () => {
      window.cancelAnimationFrame(timerId);
    };
  }, [isStreaming, messages]);

  useEffect(() => {
    persistPageTheme(pageTheme);
  }, [pageTheme]);

  useEffect(() => {
    const timerId = window.setInterval(() => {
      setDashboardClock(formatDashboardClock(new Date()));
    }, 1000);

    return () => {
      window.clearInterval(timerId);
    };
  }, []);

  useEffect(() => {
    setKanbanFilter("all");
  }, [kanbanMode]);

  const totalTasks = useMemo(
    () => digitalEmployees.reduce((sum, employee) => sum + employee.tasks, 0),
    [],
  );
  const runningTasks = useMemo(
    () =>
      digitalEmployees.filter((employee) => employee.status === "running").length,
    [],
  );
  const localHistoryCounts = useMemo(
    () =>
      Object.fromEntries(
        digitalEmployees.map((employee) => [
          employee.id,
          ensureSessionRecords(conversationStore[employee.id]).length,
        ]),
      ) as Record<string, number>,
    [conversationStore],
  );
  const localLatestSessionTitles = useMemo(
    () =>
      Object.fromEntries(
        digitalEmployees.map((employee) => {
          const sessions = ensureSessionRecords(conversationStore[employee.id]);
          return [employee.id, sessions[0]?.title || ""] as const;
        }),
      ) as Record<string, string>,
    [conversationStore],
  );
  const sidebarEmployees = useMemo(() => {
    const priorityIds = new Set<string>(sidebarEmployeePriority);
    const prioritizedEmployees = sidebarEmployeePriority
      .map((employeeId) => digitalEmployees.find((employee) => employee.id === employeeId))
      .filter(
        (employee): employee is (typeof digitalEmployees)[number] => Boolean(employee),
      );

    return [
      ...prioritizedEmployees,
      ...digitalEmployees.filter((employee) => !priorityIds.has(employee.id)),
    ];
  }, []);
  const [lastSidebarEmployeeId, setLastSidebarEmployeeId] = useState<string | null>(null);
  const currentSidebarEmployee = useMemo(() => {
    const employeeId = selectedEmployee?.id || lastSidebarEmployeeId || sidebarEmployees[0]?.id || null;
    return sidebarEmployees.find((employee) => employee.id === employeeId) || sidebarEmployees[0] || null;
  }, [lastSidebarEmployeeId, selectedEmployee?.id, sidebarEmployees]);
  const otherSidebarEmployees = useMemo(
    () => sidebarEmployees.filter((employee) => employee.id !== currentSidebarEmployee?.id),
    [currentSidebarEmployee?.id, sidebarEmployees],
  );

  useEffect(() => {
    if (currentView !== "dashboard") {
      return;
    }

    const remoteEntries = Object.entries(REMOTE_AGENT_IDS);
    if (!remoteEntries.length) {
      setDashboardRemoteHistoryCounts({});
      setDashboardRemoteSessionsMap({});
      return;
    }

    let cancelled = false;

    void Promise.all(
      remoteEntries.map(async ([employeeId, agentId]) => {
        try {
          const chats = await listChats(agentId, {
            channel: DASHBOARD_CHAT_CHANNEL,
          });
          const chatList = Array.isArray(chats) ? chats : [];
          return [
            employeeId,
            {
              count: chatList.length,
              sessions: normalizeRemoteSessions(chatList, employeeId, {
                fallbackToAllChats: true,
              }),
            },
          ] as const;
        } catch {
          return [
            employeeId,
            {
              count: localHistoryCounts[employeeId] || 0,
              sessions: null,
            },
          ] as const;
        }
      }),
    ).then((entries) => {
      if (cancelled) {
        return;
      }
      setDashboardRemoteHistoryCounts((prev) => ({
        ...prev,
        ...Object.fromEntries(entries.map(([employeeId, data]) => [employeeId, data.count])),
      }));
      const resolvedEntries = entries
        .filter((entry) => Array.isArray(entry[1].sessions))
        .map(([employeeId, data]) => [employeeId, data.sessions as SessionRecord[]]);
      setDashboardRemoteSessionsMap((prev) => ({
        ...prev,
        ...Object.fromEntries(resolvedEntries),
      }));
    });

    return () => {
      cancelled = true;
    };
  }, [currentChatId, currentView, localHistoryCounts, remoteSessions.length]);

  const dashboardHistoryCounts = useMemo(
    () =>
      Object.fromEntries(
        digitalEmployees.map((employee) => [
          employee.id,
          REMOTE_AGENT_IDS[employee.id]
            ? (dashboardRemoteHistoryCounts[employee.id] ?? localHistoryCounts[employee.id] ?? 0)
            : (localHistoryCounts[employee.id] ?? 0),
        ]),
      ) as Record<string, number>,
    [dashboardRemoteHistoryCounts, localHistoryCounts],
  );
  const dashboardLatestSessions = useMemo(
    () =>
      Object.fromEntries(
        digitalEmployees.map((employee) => [
          employee.id,
          REMOTE_AGENT_IDS[employee.id]
            ? (dashboardRemoteSessionsMap[employee.id]?.[0] ?? null)
            : (ensureSessionRecords(conversationStore[employee.id])[0] ?? null),
        ]),
      ) as Record<string, SessionRecord | null>,
    [conversationStore, dashboardRemoteSessionsMap],
  );
  const dashboardHistoryEmployee = useMemo(
    () => (dashboardHistoryEmployeeId ? getEmployeeById(dashboardHistoryEmployeeId) : null),
    [dashboardHistoryEmployeeId],
  );
  const dashboardWorkColumns = useMemo(() => buildDashboardWorkColumns(), []);
  const dashboardEmployeeSnapshots = useMemo(
    () => buildDashboardEmployeeSnapshots(dashboardHistoryCounts),
    [dashboardHistoryCounts],
  );
  const sortedOpsAlerts = useMemo(() => {
    const order: Record<PortalOpsAlertLevel, number> = {
      critical: 0,
      urgent: 1,
      warning: 2,
      info: 3,
    };

    return [...opsAlerts].sort((left, right) => order[left.level] - order[right.level]);
  }, [opsAlerts]);
  const kanbanFilterLabels = useMemo(
    () => getDashboardFilterLabels(kanbanMode),
    [kanbanMode],
  );
  const filteredDashboardWorkColumns = useMemo(() => {
    if (kanbanFilter === "all") {
      return dashboardWorkColumns;
    }

    return dashboardWorkColumns
      .map((column) => ({
        ...column,
        cards: column.cards.filter((card) =>
          kanbanFilter === "urgent" ? card.isUrgent : card.isRunning,
        ),
      }))
      .filter((column) => column.cards.length);
  }, [dashboardWorkColumns, kanbanFilter]);

  useEffect(() => {
    if (!dashboardHistoryVisible || !dashboardHistoryEmployeeId) {
      return;
    }

    if (REMOTE_AGENT_IDS[dashboardHistoryEmployeeId]) {
      setDashboardHistorySessions(dashboardRemoteSessionsMap[dashboardHistoryEmployeeId] || []);
      return;
    }

    setDashboardHistorySessions(
      ensureSessionRecords(conversationStore[dashboardHistoryEmployeeId]),
    );
  }, [
    conversationStore,
    dashboardHistoryEmployeeId,
    dashboardHistoryVisible,
    dashboardRemoteSessionsMap,
  ]);

  useEffect(() => {
    if (!alertPopupOpen) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (activeAlertTriggerRef.current?.contains(event.target as Node)) {
        return;
      }
      if (alertPopupRef.current?.contains(event.target as Node)) {
        return;
      }
      setAlertPopupOpen(false);
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [alertPopupOpen]);

  useEffect(() => {
    setAlertPopupOpen(false);
  }, [location.pathname, location.search]);

  useEffect(() => {
    if (!alertPopupOpen) {
      return;
    }

    const updateAlertPopupPosition = () => {
      const trigger = activeAlertTriggerRef.current;
      if (!trigger) {
        return;
      }

      const rect = trigger.getBoundingClientRect();
      const popupWidth = Math.min(400, window.innerWidth - 32);
      const left = Math.min(
        Math.max(16, rect.right - popupWidth),
        window.innerWidth - popupWidth - 16,
      );
      const top = Math.min(rect.bottom + 8, window.innerHeight - 24);

      setAlertPopupPosition({ top, left });
    };

    updateAlertPopupPosition();
    window.addEventListener("resize", updateAlertPopupPosition);
    const handleScroll = (event: Event) => {
      if (alertPopupRef.current?.contains(event.target as Node)) {
        return;
      }
      updateAlertPopupPosition();
    };
    window.addEventListener("scroll", handleScroll, true);

    return () => {
      window.removeEventListener("resize", updateAlertPopupPosition);
      window.removeEventListener("scroll", handleScroll, true);
    };
  }, [alertPopupOpen]);

  const filteredDashboardEmployeeSnapshots = useMemo(() => {
    if (kanbanFilter === "urgent") {
      return dashboardEmployeeSnapshots.filter((worker) => worker.runtimeState === "running");
    }
    if (kanbanFilter === "running") {
      return dashboardEmployeeSnapshots.filter((worker) => worker.runtimeState === "idle");
    }
    return dashboardEmployeeSnapshots;
  }, [dashboardEmployeeSnapshots, kanbanFilter]);

  const safeMessages = ensureObjectArray(messages);
  const safeExecutionList = ensureObjectArray<ExecutionRecord>(executionList);
  const safeCapabilities = ensureStringArray(currentEmployee?.capabilities);
  const safeQuickCommands = ensureStringArray(currentEmployee?.quickCommands);
  const showModelSelector = currentView === "chat";
  const isModelConfigMode = activeAdvancedPanel === "model-config";
  const isTokenUsageMode = activeAdvancedPanel === "token-usage";
  const isOpsExpertMode = activeAdvancedPanel === "ops-expert";
  const isMcpMode = activeAdvancedPanel === "mcp";
  const isSkillPoolMode = activeAdvancedPanel === "skill-pool";
  const isInspirationMode = activeAdvancedPanel === "inspiration";
  const isCliMode = activeAdvancedPanel === "cli";
  const effectiveMcpEmployee = isMcpMode ? (selectedEmployee || currentSidebarEmployee) : selectedEmployee;
  const effectiveMcpAgentId = effectiveMcpEmployee
    ? (REMOTE_AGENT_IDS[effectiveMcpEmployee.id] || "default")
    : "default";
  const showPortalHomeHero = isPortalHomeChat && safeMessages.length === 0;
  const mentionContext = useMemo(
    () => extractMentionQuery(inputMessage, inputCursor),
    [inputCursor, inputMessage],
  );
  const mentionSuggestions = useMemo(() => {
    if (!mentionContext) {
      return [];
    }

    return digitalEmployees
      .map((employee) => ({
        employee,
        score: scoreMentionCandidate(employee, mentionContext.query),
      }))
      .filter((item) => item.score > 0)
      .sort((left, right) => right.score - left.score)
      .slice(0, 5);
  }, [mentionContext]);

  const sessionList = (
    isRemoteEmployee
      ? remoteSessions
      : ensureSessionRecords(conversationStore[currentEmployee?.id || ""])
  ) as SessionRecord[];

  useEffect(() => {
    if (historyVisible) {
      return;
    }
    setHistoryEditingId("");
    setHistoryDraftTitle("");
    setHistoryActionSessionId("");
    setHistoryActionError("");
  }, [historyVisible]);

  const createAndActivateLocalSession = useCallback((employee: any, initialMessages: any[]) => {
    const nextSession = createConversationSession(employee, initialMessages) as SessionRecord;
    setConversationStore((prevStore) => {
      const previousSessions = ensureSessionRecords(prevStore[employee.id]);
      const nextStore: ConversationStoreState = {
        ...prevStore,
        [employee.id]: [nextSession, ...previousSessions],
      };
      saveConversationStore(nextStore);
      return nextStore;
    });
    setCurrentSessionId(nextSession.id);
    return nextSession.id;
  }, []);

  const updateMessagesAndStore = useCallback((
    nextMessages: any[],
    {
      employee = currentEmployee,
      nextSessionId = currentSessionId,
    }: {
      employee?: any;
      nextSessionId?: string;
    } = {},
  ) => {
    setMessages(nextMessages);

    if (!employee || isRemoteEmployee) {
      return;
    }

    setConversationStore((prevStore) => {
      const previousSessions = ensureSessionRecords(prevStore[employee.id]);
      const nextStore: ConversationStoreState = {
        ...prevStore,
        [employee.id]: previousSessions.map((session) =>
          session.id === nextSessionId
            ? {
                ...session,
                messages: nextMessages,
                updatedAt: new Date().toISOString(),
                title: buildSessionTitle(employee.name, nextMessages),
              }
            : session,
        ),
      };
      saveConversationStore(nextStore);
      return nextStore;
    });
  }, [currentEmployee, currentSessionId, isRemoteEmployee]);

  const queueMentionDispatch = useCallback((
    employee: any,
    content: string,
    visibleContent: string,
  ) => {
    const nextPath = buildEmployeePagePath(employee, {
      entry: null,
      view: "chat",
      panel: null,
    });

    navigate(nextPath, {
      state: {
        pendingPortalDispatch: {
          token: `pending-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          targetEmployeeId: employee.id,
          content,
          visibleContent,
        },
      } satisfies PortalLocationState,
    });
  }, [navigate]);

  const handlePortalAlertAction = useCallback((alert: PortalOpsAlert) => {
    setAlertPopupOpen(false);
    setOpsAlerts((currentAlerts) => currentAlerts.filter((item) => item.id !== alert.id));

    const employee = getEmployeeById(alert.employeeId);
    if (!employee) {
      return;
    }

    if (alert.routeEntry === ALARM_WORKORDER_ENTRY) {
      navigateToEmployeePage(employee, {
        entry: ALARM_WORKORDER_ENTRY,
        view: "chat",
        panel: null,
      });
      return;
    }

    queueMentionDispatch(
      employee,
      alert.dispatchContent || alert.message,
      alert.visibleContent || alert.message,
    );
  }, [navigateToEmployeePage, queueMentionDispatch]);

  const handleClearPortalAlerts = useCallback((event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    setOpsAlerts([]);
    setAlertPopupOpen(false);
  }, []);

  const handleToggleAlertPopup = useCallback((event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();

    const trigger = event.currentTarget;
    const isSameTrigger = activeAlertTriggerRef.current === trigger;
    const popupWidth = Math.min(400, window.innerWidth - 32);
    const rect = trigger.getBoundingClientRect();
    const left = Math.min(
      Math.max(16, rect.right - popupWidth),
      window.innerWidth - popupWidth - 16,
    );

    activeAlertTriggerRef.current = trigger;
    setAlertPopupPosition({
      top: Math.min(rect.bottom + 8, window.innerHeight - 24),
      left,
    });
    setAlertPopupOpen((value) => (isSameTrigger ? !value : true));
  }, []);

  const runLocalEmployeeFlow = useCallback((
    employee: any,
    content: string,
    visibleContent: string,
  ) => {
    let nextSessionId = currentSessionId;
    if (!nextSessionId) {
      nextSessionId = createAndActivateLocalSession(
        employee,
        messages.length ? messages : [createWelcomeMessage(employee)],
      );
    }

    const userMessage = createUserMessage(visibleContent);
    const workflow =
      employeeWorkflows[employee.id as keyof typeof employeeWorkflows] || [];
    const result =
      employeeResults[employee.id as keyof typeof employeeResults] || null;
    const processingMessage = {
      ...createAgentMessage(employee, {
        id: `agent-${Date.now()}`,
        content: workflow.length ? "收到！我正在为您处理..." : buildPortalAssistantReply(content),
      }),
      workflow: [...workflow],
      currentStep: 0,
      workflowDone: false,
      stepTimes: [] as string[],
      result: null,
    };

    const initialQueue = [...messages, userMessage, processingMessage];
    updateMessagesAndStore(initialQueue, {
      employee,
      nextSessionId,
    });

    if (!workflow.length) {
      return;
    }

    let step = 0;
    const interval = window.setInterval(() => {
      setMessages((prevMessages) => {
        const nextMessages = prevMessages.map((message) => {
          if (message.id !== processingMessage.id) {
            return message;
          }

          if (step < processingMessage.workflow.length) {
            return {
              ...message,
              currentStep: step,
              stepTimes: [
                ...(message.stepTimes || []),
                `${Math.floor(Math.random() * 2) + 1}s`,
              ],
            };
          }

          return {
            ...message,
            content: "",
            workflowDone: true,
            result,
          };
        });

        if (step >= processingMessage.workflow.length) {
          window.clearInterval(interval);
          window.setTimeout(() => {
            updateMessagesAndStore(nextMessages, {
              employee,
              nextSessionId,
            });
          }, 0);
        }

        return nextMessages;
      });
      step += 1;
    }, 800);
  }, [createAndActivateLocalSession, currentSessionId, messages, updateMessagesAndStore]);

  const dispatchActiveMessage = useCallback(async (
    content: string,
    {
      visibleContent = content,
      targetEmployee = currentEmployee,
    }: {
      visibleContent?: string;
      targetEmployee?: any;
    } = {},
  ) => {
    if (!content || !targetEmployee) {
      return false;
    }

    if (isRemoteEmployee && targetEmployee.id === currentEmployee.id) {
      return handleRemoteSendMessage(content, {
        visibleContent,
      });
    }

    runLocalEmployeeFlow(targetEmployee, content, visibleContent);
    return true;
  }, [
    currentEmployee,
    handleRemoteSendMessage,
    isRemoteEmployee,
    runLocalEmployeeFlow,
  ]);

  useEffect(() => {
    const pendingDispatch = locationState?.pendingPortalDispatch;
    if (!pendingDispatch || !currentEmployee) {
      return;
    }

    if (pendingDispatch.targetEmployeeId !== currentEmployee.id) {
      return;
    }

    if (handledPendingDispatchRef.current === pendingDispatch.token) {
      return;
    }

    handledPendingDispatchRef.current = pendingDispatch.token;

    navigate(`${location.pathname}${location.search}`, {
      replace: true,
      state: {},
    });

    window.setTimeout(() => {
      void dispatchActiveMessage(pendingDispatch.content, {
        visibleContent: pendingDispatch.visibleContent,
      });
    }, 0);
  }, [
    currentEmployee,
    dispatchActiveMessage,
    location.pathname,
    location.search,
    locationState,
    navigate,
  ]);

  useEffect(() => {
    const openHistoryForEmployeeId = locationState?.openHistoryForEmployeeId;
    if (!openHistoryForEmployeeId || !currentEmployee) {
      return;
    }

    if (openHistoryForEmployeeId !== currentEmployee.id) {
      return;
    }

    navigate(`${location.pathname}${location.search}`, {
      replace: true,
      state: {},
    });
    void handleOpenHistory();
  }, [
    currentEmployee,
    handleOpenHistory,
    location.pathname,
    location.search,
    locationState,
    navigate,
  ]);

  useEffect(() => {
    setMentionActiveIndex(0);
  }, [mentionContext?.query]);

  useEffect(() => {
    if (!selectedEmployee?.id) {
      return;
    }
    setLastSidebarEmployeeId(selectedEmployee.id);
    setEmployeeDropdownOpen(false);
  }, [selectedEmployee?.id]);

  useEffect(() => {
    if (!isMcpMode || selectedEmployee || !currentSidebarEmployee?.id) {
      return;
    }

    navigate(
      buildPortalSectionPath("mcp", {
        entry: currentEntry,
        employeeId: currentSidebarEmployee.id,
      }),
      { replace: true },
    );
  }, [
    currentEntry,
    currentSidebarEmployee?.id,
    isMcpMode,
    navigate,
    selectedEmployee,
  ]);

  useEffect(() => {
    if (!employeeDropdownOpen) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!employeeDropdownRef.current?.contains(event.target as Node)) {
        setEmployeeDropdownOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [employeeDropdownOpen]);

  const getEmployeeStatusBadgeClassName = useCallback((employee: any) => {
    if (employee.urgent) {
      return "status-badge urgent";
    }
    if (employee.status === "running") {
      return "status-badge running";
    }
    return "status-badge stopped";
  }, []);

  const getEmployeeStatusLabel = useCallback((employee: any) => {
    if (employee.urgent) {
      return "紧急";
    }
    if (employee.status === "running") {
      return "运行中";
    }
    return "已停止";
  }, []);

  const renderSidebarEmployeeCard = useCallback((
    employee: any,
    {
      active = false,
      expandable = false,
      expanded = false,
      onClick,
      onToggleExpand,
    }: {
      active?: boolean;
      expandable?: boolean;
      expanded?: boolean;
      onClick: () => void;
      onToggleExpand?: () => void;
    },
  ) => (
    <div
      key={employee.id}
      role="button"
      tabIndex={0}
      className={
        active
          ? "agent-card active agent-card-selector"
          : "agent-card agent-card-selector"
      }
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onClick();
        }
      }}
    >
      <span className={getEmployeeStatusBadgeClassName(employee)}>
        {getEmployeeStatusLabel(employee)}
      </span>

      <div className="agent-header">
        <DigitalEmployeeAvatar employee={employee} />
        <div className="agent-info">
          <h3>{employee.name}</h3>
          <p>{employee.desc}</p>
        </div>
        {expandable ? (
          <button
            type="button"
            className={expanded ? "agent-card-chevron open" : "agent-card-chevron"}
            aria-label={expanded ? "收起员工切换" : "展开员工切换"}
            aria-expanded={expanded}
            onClick={(event) => {
              event.stopPropagation();
              onToggleExpand?.();
            }}
          >
            <i className={`fas ${expanded ? "fa-chevron-up" : "fa-chevron-down"}`} />
          </button>
        ) : null}
      </div>
      <div className="agent-stats">
        <div className="stat-item">
          <i className="fas fa-chart-line" />
          <span className="stat-value">{employee.tasks}</span> 执行
        </div>
        <div className="stat-item">
          <i className="fas fa-check-circle" />
          <span className="stat-value" style={{ color: "var(--success)" }}>
            {employee.success}
          </span>
        </div>
      </div>
    </div>
  ), [getEmployeeStatusBadgeClassName, getEmployeeStatusLabel]);

  const prefillEmployeeMention = useCallback((employee: any) => {
    const rawContent = String(inputMessage || "").trim();
    const mentionResult = extractMentionTarget(rawContent);
    const nextContent = mentionResult.employee ? mentionResult.cleanContent : rawContent;
    const nextValue = nextContent ? `@${employee.name} ${nextContent}` : `@${employee.name} `;
    const nextCursor = nextValue.length;

    setInputMessage(nextValue);
    setInputCursor(nextCursor);

    window.requestAnimationFrame(() => {
      homeComposerRef.current?.focus();
      homeComposerRef.current?.setSelectionRange(nextCursor, nextCursor);
    });
  }, [inputMessage]);

  const applyMentionSuggestion = (employeeName: string) => {
    if (!mentionContext) {
      return;
    }

    const nextValue = `${inputMessage.slice(0, mentionContext.start)}@${employeeName} ${inputMessage.slice(mentionContext.end)}`;
    const nextCursor = mentionContext.start + employeeName.length + 2;
    setInputMessage(nextValue);
    setInputCursor(nextCursor);

    window.requestAnimationFrame(() => {
      const activeInput = showPortalHomeHero ? homeComposerRef.current : chatInputRef.current;
      activeInput?.focus();
      activeInput?.setSelectionRange(nextCursor, nextCursor);
    });
  };

  const handleInputSelection = (
    event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>
      | React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>
      | React.MouseEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => {
    const target = event.currentTarget;
    setInputCursor(target.selectionStart ?? target.value.length);
  };

  const handleComposerKeyDown = (
    event: React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>,
    { multiline = false }: { multiline?: boolean } = {},
  ) => {
    if (mentionSuggestions.length) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setMentionActiveIndex((prev) => (prev + 1) % mentionSuggestions.length);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setMentionActiveIndex((prev) =>
          prev === 0 ? mentionSuggestions.length - 1 : prev - 1,
        );
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        const candidate = mentionSuggestions[mentionActiveIndex]?.employee;
        if (candidate) {
          applyMentionSuggestion(candidate.name);
        }
        return;
      }
      if (event.key === "Escape") {
        setInputCursor(null);
        return;
      }
    }

    if (event.key === "Enter" && (!multiline || !event.shiftKey) && !isStreaming) {
      event.preventDefault();
      void handleSendMessage();
    }
  };

  const handleSendMessage = async (preset = "") => {
    const rawContent = (preset || inputMessage).trim();
    if (!rawContent || !currentEmployee) {
      return;
    }

    if (!preset) {
      setInputMessage("");
    }

    const mentionResult = extractMentionTarget(rawContent);
    if (mentionResult.employee) {
      const shouldUseAgentCollaboration = Boolean(
        selectedEmployee
        && isRemoteEmployee
        && remoteAgentId
        && mentionResult.employee.id !== currentEmployee.id,
      );

      if (shouldUseAgentCollaboration) {
        await dispatchActiveMessage(
          buildMentionCollaborationPrompt({
            currentEmployee,
            currentAgentId: remoteAgentId,
            targetEmployee: mentionResult.employee,
            userRequest: mentionResult.cleanContent,
          }),
          {
            visibleContent: mentionResult.visibleContent,
          },
        );
        return;
      }

      if (!mentionResult.cleanContent) {
        navigateToEmployeePage(mentionResult.employee, {
          entry: null,
          view: "chat",
          panel: null,
        });
        return;
      }

      if (mentionResult.employee.id !== currentEmployee.id) {
        queueMentionDispatch(
          mentionResult.employee,
          mentionResult.cleanContent,
          mentionResult.visibleContent,
        );
        return;
      }

      await dispatchActiveMessage(mentionResult.cleanContent, {
        visibleContent: mentionResult.visibleContent,
      });
      return;
    }

    await dispatchActiveMessage(rawContent);
  };

  const handleSelectHistory = async (session: SessionRecord) => {
    if (!currentEmployee) {
      return;
    }

    if (!isRemoteEmployee) {
      setCurrentSessionId(session.id);
      setMessages(session.messages || []);
      setHistoryVisible(false);
      return;
    }

    await handleSelectRemoteHistory(session);
  };

  useEffect(() => {
    const openSession = locationState?.openSession;
    if (!openSession || !currentEmployee) {
      return;
    }

    if (openSession.employeeId !== currentEmployee.id) {
      return;
    }

    const openKey = `${openSession.employeeId}:${openSession.sessionId}`;
    const availableSessions = isRemoteEmployee
      ? remoteSessions
      : ensureSessionRecords(conversationStore[currentEmployee.id]);
    const targetSession = availableSessions.find((session) => session.id === openSession.sessionId);

    if (targetSession) {
      handledDashboardSessionOpenRef.current = "";
      navigate(`${location.pathname}${location.search}`, {
        replace: true,
        state: {},
      });
      void handleSelectHistory(targetSession);
      return;
    }

    if (isRemoteEmployee && handledDashboardSessionOpenRef.current !== openKey) {
      handledDashboardSessionOpenRef.current = openKey;
      void refreshRemoteSessions(false);
    }
  }, [
    conversationStore,
    currentEmployee,
    handleSelectHistory,
    isRemoteEmployee,
    location.pathname,
    location.search,
    locationState,
    navigate,
    refreshRemoteSessions,
    remoteSessions,
  ]);

  const handleStartNewConversation = useCallback(() => {
    if (!currentEmployee) {
      return;
    }

    setInputMessage("");
    setExecutionVisible(false);

    if (isAlarmWorkbenchMode) {
      resetAlarmWorkbench();
      resetRemoteState({
        initialMessages: [
          createAlarmWorkorderMessage(currentEmployee, {
            content: "告警已触发，我正在为您查询待处置工单...",
            workorders: [],
            workordersLoading: true,
            workordersError: "",
          }),
        ],
      });
      void loadAlarmWorkorders();
      return;
    }

    if (isRemoteEmployee) {
      resetRemoteState({
        initialMessages: [createWelcomeMessage(currentEmployee)],
      });
      return;
    }

    const initialMessages = [createWelcomeMessage(currentEmployee)];
    createAndActivateLocalSession(currentEmployee, initialMessages);
    setMessages(initialMessages);
    setHistoryVisible(false);
  }, [
    createAndActivateLocalSession,
    currentEmployee,
    isAlarmWorkbenchMode,
    isRemoteEmployee,
    loadAlarmWorkorders,
    resetAlarmWorkbench,
    resetRemoteState,
    setHistoryVisible,
  ]);

  const handleStartHistoryRename = useCallback((session: SessionRecord) => {
    setHistoryActionError("");
    setHistoryEditingId(session.id);
    setHistoryDraftTitle(session.title);
  }, []);

  const handleCancelHistoryRename = useCallback(() => {
    setHistoryEditingId("");
    setHistoryDraftTitle("");
    setHistoryActionError("");
  }, []);

  const handleSubmitHistoryRename = useCallback(async (session: SessionRecord) => {
    if (!currentEmployee) {
      return;
    }

    const nextTitle = historyDraftTitle.trim();
    if (!nextTitle) {
      setHistoryActionError("会话名称不能为空");
      return;
    }

    if (nextTitle === session.title) {
      handleCancelHistoryRename();
      return;
    }

    setHistoryActionSessionId(session.id);
    setHistoryActionError("");

    try {
      if (isRemoteEmployee) {
        await updateChat(remoteAgentId || undefined, session.id, { name: nextTitle });
        await refreshRemoteSessions(false);
      } else {
        const previousSessions = ensureSessionRecords(conversationStore[currentEmployee.id]);
        const nextSessions = previousSessions.map((item) =>
          item.id === session.id
            ? {
                ...item,
                title: nextTitle,
                updatedAt: new Date().toISOString(),
              }
            : item,
        );
        const nextStore: ConversationStoreState = {
          ...conversationStore,
          [currentEmployee.id]: nextSessions,
        };
        saveConversationStore(nextStore);
        setConversationStore(nextStore);
      }

      setHistoryEditingId("");
      setHistoryDraftTitle("");
    } catch (error: any) {
      setHistoryActionError(error?.message || "会话名称更新失败，请稍后重试");
    } finally {
      setHistoryActionSessionId("");
    }
  }, [
    conversationStore,
    currentEmployee,
    handleCancelHistoryRename,
    historyDraftTitle,
    isRemoteEmployee,
    refreshRemoteSessions,
    remoteAgentId,
  ]);

  const handleDeleteHistorySession = useCallback(async (session: SessionRecord) => {
    if (!currentEmployee) {
      return;
    }

    if (!window.confirm(`确认删除“${session.title}”吗？`)) {
      return;
    }

    setHistoryActionSessionId(session.id);
    setHistoryActionError("");

    try {
      if (isRemoteEmployee) {
        const deletingCurrentSession = session.id === currentChatId;
        if (deletingCurrentSession) {
          stopActiveStream(false, { silent: true });
        }
        await deleteChat(remoteAgentId || undefined, session.id);
        if (deletingCurrentSession) {
          resetRemoteState({
            initialMessages: [createWelcomeMessage(currentEmployee)],
            clearHistoryError: false,
          });
          setHistoryVisible(true);
        }
        await refreshRemoteSessions(!deletingCurrentSession);
      } else {
        const previousSessions = ensureSessionRecords(conversationStore[currentEmployee.id]);
        const nextSessions = previousSessions.filter((item) => item.id !== session.id);
        const nextStore: ConversationStoreState = {
          ...conversationStore,
          [currentEmployee.id]: nextSessions,
        };
        saveConversationStore(nextStore);
        setConversationStore(nextStore);

        if (session.id === currentSessionId) {
          const nextActiveSession = nextSessions[0];
          if (nextActiveSession) {
            setCurrentSessionId(nextActiveSession.id);
            setMessages(nextActiveSession.messages || []);
          } else {
            setCurrentSessionId("");
            setMessages([createWelcomeMessage(currentEmployee)]);
          }
        }
      }

      if (historyEditingId === session.id) {
        setHistoryEditingId("");
        setHistoryDraftTitle("");
      }
    } catch (error: any) {
      setHistoryActionError(error?.message || "删除会话失败，请稍后重试");
    } finally {
      setHistoryActionSessionId("");
    }
  }, [
    conversationStore,
    currentChatId,
    currentEmployee,
    currentSessionId,
    historyEditingId,
    isRemoteEmployee,
    refreshRemoteSessions,
    remoteAgentId,
    resetRemoteState,
    setHistoryVisible,
    stopActiveStream,
  ]);

  const handleOpenExecutionHistory = (type: "executions" | "running" | "success") => {
    if (type === "executions") {
      setExecutionTitle("执行历史 - 全部任务");
      setExecutionList(executionHistory);
    } else if (type === "running") {
      setExecutionTitle("执行历史 - 进行中");
      setExecutionList(
        executionHistory.filter((item) => item.status === "running"),
      );
    } else {
      setExecutionTitle("执行历史 - 成功率");
      setExecutionList(
        executionHistory.filter((item) => item.status === "success"),
      );
    }
    setExecutionVisible(true);
  };

  const handleOpenTaskEmployeeChat = (employeeId: string, session?: SessionRecord | null) => {
    const employee = getEmployeeById(employeeId);
    if (!employee) {
      return;
    }
    navigateToEmployeePage(employee, {
      view: "chat",
      panel: null,
      state: session
        ? {
            openSession: {
              employeeId,
              sessionId: session.id,
            },
          }
        : undefined,
    });
  };

  const handleOpenDashboardEmployeeHistory = async (employeeId: string) => {
    const employee = getEmployeeById(employeeId);
    if (!employee) {
      return;
    }

    setDashboardHistoryEmployeeId(employee.id);
    setDashboardHistoryVisible(true);
    setDashboardHistoryError("");

    if (!REMOTE_AGENT_IDS[employee.id]) {
      setDashboardHistoryLoading(false);
      setDashboardHistorySessions(ensureSessionRecords(conversationStore[employee.id]));
      return;
    }

    const cachedSessions = dashboardRemoteSessionsMap[employee.id];
    if (cachedSessions) {
      setDashboardHistoryLoading(false);
      setDashboardHistorySessions(cachedSessions);
      return;
    }

    setDashboardHistoryLoading(true);
    try {
      const chats = await listChats(REMOTE_AGENT_IDS[employee.id], {
        channel: DASHBOARD_CHAT_CHANNEL,
      });
      const normalizedSessions = normalizeRemoteSessions(
        Array.isArray(chats) ? chats : [],
        employee.id,
        { fallbackToAllChats: true },
      );
      setDashboardRemoteSessionsMap((prev) => ({
        ...prev,
        [employee.id]: normalizedSessions,
      }));
      setDashboardHistorySessions(normalizedSessions);
    } catch (error: any) {
      setDashboardHistoryError(error?.message || "获取已处理任务失败，请稍后重试");
      setDashboardHistorySessions([]);
    } finally {
      setDashboardHistoryLoading(false);
    }
  };

  const handleSelectDashboardHistory = (employeeId: string, session: SessionRecord) => {
    setDashboardHistoryVisible(false);
    setDashboardHistoryEmployeeId("");
    setDashboardHistorySessions([]);
    setDashboardHistoryError("");
    handleOpenTaskEmployeeChat(employeeId, session);
  };

  const renderAlertBell = () => (
    <div className="alert-bell-wrap">
      <button
        type="button"
        className={opsAlerts.length ? "alert-bell has-alerts" : "alert-bell"}
        onClick={handleToggleAlertPopup}
        aria-label="查看运维告警"
        title="运维告警"
      >
        {alertBellIcon}
        <span className="bell-badge">{opsAlerts.length > 99 ? "99+" : opsAlerts.length}</span>
      </button>
    </div>
  );

  const alertPopup = alertPopupOpen && alertPopupPosition && typeof document !== "undefined"
    ? createPortal(
        <div
          ref={alertPopupRef}
          className={pageTheme === "dark" ? "portal-alert-popup theme-dark show" : "portal-alert-popup show"}
          style={{
            top: alertPopupPosition.top,
            left: alertPopupPosition.left,
          }}
          onClick={(event) => event.stopPropagation()}
        >
          <div className="alert-popup-header">
            <div className="alert-popup-title">
              {alertBellIcon}
              <span>运维告警</span>
              {opsAlerts.length ? <span className="alert-count">{opsAlerts.length}</span> : null}
            </div>
            {opsAlerts.length ? (
              <button type="button" className="alert-popup-clear" onClick={handleClearPortalAlerts}>
                全部清除
              </button>
            ) : null}
          </div>
          <div className="alert-popup-body">
            {sortedOpsAlerts.length ? (
              sortedOpsAlerts.map((alert) => {
                const employee = getEmployeeById(alert.employeeId);
                const employeeColor = getDashboardEmployeeColor(alert.employeeId);

                return (
                  <button
                    key={alert.id}
                    type="button"
                    className="alert-popup-item"
                    onClick={() => handlePortalAlertAction(alert)}
                  >
                    <div
                      className="alert-popup-item-icon"
                      style={{
                        background: `${employeeColor}20`,
                        color: employeeColor,
                      }}
                    >
                      {employee ? (
                        <DigitalEmployeeAvatar
                          employee={employee}
                          className="portal-alert-popup-avatar"
                        />
                      ) : (
                        alertBellIcon
                      )}
                    </div>
                    <div className="alert-popup-item-body">
                      <div className="alert-popup-item-msg">{alert.message}</div>
                      <div className="alert-popup-item-meta">
                        <span className="alert-popup-item-emp" style={{ color: employeeColor }}>
                          {employee?.name || alert.employeeId}
                        </span>
                        <span
                          className="alert-popup-item-level"
                          style={{
                            color: PORTAL_ALERT_LEVEL_COLORS[alert.level],
                            background: `${PORTAL_ALERT_LEVEL_COLORS[alert.level]}15`,
                            borderColor: `${PORTAL_ALERT_LEVEL_COLORS[alert.level]}30`,
                          }}
                        >
                          {PORTAL_ALERT_LEVEL_LABELS[alert.level]}
                        </span>
                        <span className="alert-popup-item-time">{alert.timeLabel}</span>
                      </div>
                    </div>
                    <span className="alert-popup-item-go" aria-hidden="true">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <polyline points="9 18 15 12 9 6" />
                      </svg>
                    </span>
                  </button>
                );
              })
            ) : (
              <div className="alert-popup-empty">暂无待处理告警</div>
            )}
          </div>
        </div>,
        document.body,
      )
    : null;

  if (!currentEmployee) {
    return null;
  }

  return (
    <DigitalEmployeeErrorBoundary>
      <div
        className={
          pageTheme === "dark" ? "portal-digital-employee theme-dark" : "portal-digital-employee"
        }
      >
      <div className="bg-effects">
        <div className="bg-gradient" />
        <div className="grid-bg" />
      </div>

      <div className="app-container">
        <div className="sidebar">
          <button
            type="button"
            className={isPortalHomeChat ? "logo active" : "logo"}
            onClick={() =>
              navigateToPortalHome({
                entry: null,
                view: "chat",
                panel: null,
              })
            }
          >
            <div className="logo-icon">
              <img src={portalLogo} alt={portalAppTitle} className="logo-icon-image" />
            </div>
            <div className="logo-text">
              <h1>{portalAppTitle}</h1>
              <span>智能 · 高效 · 自动化</span>
            </div>
          </button>

          <div className="view-tabs">
            <button
              className={currentView === "overview" ? "view-tab active" : "view-tab"}
              onClick={() => {
                updateCurrentEmployeeRoute({
                  view: "overview",
                  panel: null,
                });
              }}
            >
              <i className="fas fa-chart-line" />
              <span>总览</span>
            </button>
            <button
              className={currentView === "dashboard" ? "view-tab active" : "view-tab"}
              onClick={() => {
                updateCurrentEmployeeRoute({
                  view: "dashboard",
                  panel: null,
                });
              }}
            >
              <i className="fas fa-chart-pie" />
              <span>看板</span>
            </button>
          </div>

          <div className="agents-title">
            <span className="agents-title-copy">
              <i className="fas fa-users" />
              数字员工矩阵
            </span>
          </div>

          <div className="agent-list">
            <div
              ref={employeeDropdownRef}
              className={
                employeeDropdownOpen
                  ? "agent-dropdown agent-dropdown-open"
                  : "agent-dropdown"
              }
            >
              {currentSidebarEmployee ? renderSidebarEmployeeCard(currentSidebarEmployee, {
                active: true,
                expandable: true,
                expanded: employeeDropdownOpen,
                onClick: () => {
                  setEmployeeDropdownOpen(false);
                  navigateToEmployeePage(currentSidebarEmployee, {
                    view: "chat",
                    panel: null,
                  });
                },
                onToggleExpand: () => setEmployeeDropdownOpen((prev) => !prev),
              }) : null}

              {employeeDropdownOpen ? (
                <div className="agent-dropdown-menu">
                  {otherSidebarEmployees.map((employee) =>
                    renderSidebarEmployeeCard(employee, {
                      onClick: () => {
                        setEmployeeDropdownOpen(false);
                        navigateToEmployeePage(employee, {
                          view: "chat",
                          panel: null,
                        });
                      },
                    }),
                  )}
                </div>
              ) : null}
            </div>
          </div>

          <AdvancedModelEntry
            activeModelLabel={activeModelLabel}
            activeProviderName={activeProviderName}
            isActive={isModelConfigMode}
            isCronJobsActive={currentView === "tasks"}
            isTokenUsageActive={isTokenUsageMode}
            isOpsExpertActive={isOpsExpertMode}
            isMcpActive={isMcpMode}
            isSkillPoolActive={isSkillPoolMode}
            isInspirationActive={isInspirationMode}
            isCliActive={isCliMode}
            onOpenConfig={openModelConfig}
            onOpenCronJobs={() =>
              updateCurrentEmployeeRoute({
                view: "tasks",
                panel: null,
              })
            }
            onOpenTokenUsage={() =>
              updateCurrentEmployeeRoute({
                panel: "token-usage",
              })
            }
            onOpenOpsExpert={() =>
              updateCurrentEmployeeRoute({
                panel: "ops-expert",
              })
            }
            onOpenMcp={() =>
              updateCurrentEmployeeRoute({
                panel: "mcp",
              })
            }
            onOpenSkillPool={openSkillPool}
            onOpenInspiration={openInspiration}
            onOpenCli={openCli}
          />
        </div>

        <div
          className={
            isModelConfigMode || isTokenUsageMode || isOpsExpertMode || isMcpMode || isSkillPoolMode || isInspirationMode || isCliMode
              ? "main-content advanced-page-mode"
              : currentView === "chat"
                ? "main-content"
                : currentView === "tasks"
                  ? "main-content card-mode task-page-mode"
                  : "main-content card-mode"
          }
        >
          {!isPortalHomeChat && currentView !== "dashboard" ? (
            <div className="portal-global-quick-actions">
              {renderAlertBell()}
              <button
                type="button"
                className="ops-board-theme-toggle"
                onClick={() => setPageTheme((value) => (value === "light" ? "dark" : "light"))}
                aria-label="切换整页主题"
                title="切换整页主题"
              >
                {themeToggleIcon}
              </button>
            </div>
          ) : null}
          {isModelConfigMode ? (
              <ModelConfigModal
                open
                activeProviderId={activeProviderId}
                displayProviders={displayProviders}
                loading={modelsLoading}
                switching={modelsSwitching}
                submitting={modelsSubmitting}
                disabled={isCreatingChat || isStreaming}
                notice={modelNotice}
                onRefresh={() => void fetchModelState()}
                onSubmitProvider={handleSaveProvider}
                onSubmitModel={handleAddModel}
                onDeleteProvider={handleDeleteProvider}
                onRevokeProviderAuth={handleRevokeProviderAuth}
                onApplyBuiltinApiKey={handleApplyBuiltinApiKey}
                onRemoveModel={handleRemoveModel}
                onConfigureModel={handleConfigureModel}
                onTestProvider={handleTestProvider}
                onTestModel={handleTestModel}
                onProbeMultimodal={handleProbeMultimodal}
                onDiscoverModels={handleDiscoverModels}
              />
          ) : isTokenUsageMode ? (
            <TokenUsagePanel
              pageTheme={pageTheme}
              currentEmployeeName={selectedEmployee ? currentEmployee.name : "全局"}
            />
          ) : isOpsExpertMode ? (
            <OpsExpertPanel />
          ) : isMcpMode ? (
            <McpPanel
              agentId={effectiveMcpAgentId}
              currentEmployeeId={effectiveMcpEmployee?.id || null}
              currentEmployeeName={effectiveMcpEmployee?.name || currentEmployee.name}
              onSwitchEmployee={switchMcpEmployee}
            />
          ) : isSkillPoolMode ? (
            <SkillPoolPanel />
          ) : isInspirationMode ? (
            <InspirationPanel
              onOpenEmployeeChat={openEmployeeChat}
              onOpenView={(view) =>
                updateCurrentEmployeeRoute({
                  view,
                  panel: null,
                })
              }
              onOpenPanel={(panel) =>
                updateCurrentEmployeeRoute({
                  panel,
                })
              }
            />
          ) : isCliMode ? (
            <CliTerminalPanel
              employees={sidebarEmployees}
              activeEmployeeId={selectedEmployee?.id || currentSidebarEmployee?.id || null}
              onOpenEmployeeChat={openEmployeeChat}
            />
          ) : (
            <>
          {!isPortalHomeChat ? (
            <div className="top-bar">
              <div className="active-agent-title">
                <div className="active-agent-avatar">
                  <i
                    className={`fas ${
                      currentView === "overview"
                        ? "fa-chart-line"
                        : currentView === "dashboard"
                        ? "fa-chart-pie"
                        : currentView === "tasks"
                          ? "fa-clock"
                          : currentEmployee.icon
                    }`}
                  />
                </div>
                <div className="active-agent-info">
                  <h2>
                    {currentView === "overview"
                      ? "数字总览"
                      : currentView === "dashboard"
                        ? "数字员工看板"
                        : currentView === "tasks"
                          ? "定时任务"
                          : currentEmployee.name}
                  </h2>
                  <span>
                    {currentView === "overview"
                      ? "查看整体态势、告警与业务健康"
                      : currentView === "dashboard"
                        ? "查看实时任务概览和泳道看板"
                        : currentView === "tasks"
                          ? "查看和管理 CoPaw 定时任务"
                          : isAlarmWorkbenchMode
                            ? "告警触发后自动生成的待处置工单视图"
                            : currentEmployee.desc}
                  </span>
                </div>
              </div>
              <div className="top-bar-actions" />
            </div>
          ) : null}

          {currentView === "overview" ? (
            <OverviewPanel
              pageTheme={pageTheme}
              onOpenEmployeeChat={handleOpenTaskEmployeeChat}
            />
          ) : null}

          {currentView === "dashboard" ? (
            <div className="kanban-shell">
              <div className="kanban-toolbar main-header">
                <div className="kanban-main-title main-title">
                  运维看板
                  <small>
                    {kanbanMode === "employee"
                      ? "数字员工维度 · 当前工作状态"
                      : "工作维度 · 实时任务概览"}
                  </small>
                </div>
                <div className="ops-filter-bar">
                  <div className="ops-filter-left">
                    <div className="ops-filter-tabs ops-dimension-tabs">
                      <button
                        type="button"
                        className={kanbanMode === "work" ? "ops-filter-tab active" : "ops-filter-tab"}
                        onClick={() => setKanbanMode("work")}
                      >
                        工作维度
                      </button>
                      <button
                        type="button"
                        className={kanbanMode === "employee" ? "ops-filter-tab active" : "ops-filter-tab"}
                        onClick={() => setKanbanMode("employee")}
                      >
                        数字员工维度
                      </button>
                    </div>
                    <div className="ops-filter-tabs">
                      {(Object.entries(kanbanFilterLabels) as [DashboardKanbanFilter, string][])
                        .map(([filterId, label]) => (
                          <button
                            key={`kanban-filter-${filterId}`}
                            type="button"
                            className={kanbanFilter === filterId ? "ops-filter-tab active" : "ops-filter-tab"}
                            onClick={() => setKanbanFilter(filterId)}
                          >
                            {label}
                          </button>
                        ))}
                    </div>
                  </div>
                </div>
                <div className="kanban-header-actions main-header-actions">
                  <div className="ops-clock">
                    <span className="ops-clock-dot" />
                    <span>{dashboardClock}</span>
                  </div>
                  {renderAlertBell()}
                  <button
                    type="button"
                    className="kanban-theme-toggle theme-toggle"
                    onClick={() => setPageTheme((value) => (value === "light" ? "dark" : "light"))}
                    aria-label="切换整页主题"
                    title="切换整页主题"
                  >
                    {themeToggleIcon}
                  </button>
                </div>
              </div>

              {kanbanMode === "employee" ? (
                <div className="kanban-board employee-dimension">
                  {filteredDashboardEmployeeSnapshots.length ? (
                    filteredDashboardEmployeeSnapshots.map((worker) => {
                      const latestSession = dashboardLatestSessions[worker.id];
                      const runtimeLabel = worker.urgent
                        ? "紧急处理中"
                        : worker.runtimeState === "running"
                          ? "运行中"
                          : "闲置中";
                      const runtimeColor = worker.urgent
                        ? "#f97316"
                        : worker.runtimeState === "running"
                          ? "#22c55e"
                          : "#94a3b8";
                      const runtimeBg = worker.urgent
                        ? "rgba(249, 115, 22, 0.14)"
                        : worker.runtimeState === "running"
                          ? "rgba(34, 197, 94, 0.14)"
                          : "rgba(100, 116, 139, 0.14)";
                      const runtimeTextColor = worker.urgent
                        ? "#fb923c"
                        : worker.runtimeState === "running"
                          ? "#86efac"
                          : "#cbd5e1";

                      return (
                        <div
                          key={`kanban-worker-${worker.id}`}
                          className="kanban-card employee-worker-card"
                        >
                          <span
                            className="kanban-card-stripe"
                            style={{ background: worker.color }}
                            aria-hidden="true"
                          />
                          <div className="kanban-emp">
                            <DigitalEmployeeAvatar
                              employee={getEmployeeById(worker.id)}
                              className="kanban-emp-avatar"
                            />
                            <div className="kanban-emp-copy">
                              <div className="kanban-card-title compact">{worker.name}</div>
                              <div className="kanban-emp-name">{worker.desc}</div>
                            </div>
                          </div>
                          <div className="kanban-worker-status">
                            <span
                              className="kanban-worker-status-dot"
                              style={{ background: runtimeColor, color: runtimeColor }}
                            />
                            <span className="kanban-worker-status-text">{runtimeLabel}</span>
                            <span className="kanban-card-time">{worker.updatedAt}</span>
                          </div>
                          <div className="kanban-card-title">{worker.currentJob}</div>
                          <div className="kanban-progress">
                            <div className="kanban-progress-bar">
                              <div
                                className="kanban-progress-fill"
                                style={{
                                  width: `${worker.progress}%`,
                                  background: `linear-gradient(90deg, ${worker.color}, ${worker.color}cc)`,
                                }}
                              />
                            </div>
                            <div className="kanban-progress-label">
                              <span>当前工作进度</span>
                              <span style={{ color: worker.color, fontWeight: 600 }}>
                                {worker.progress}%
                              </span>
                            </div>
                          </div>
                          <div className="kanban-worker-summary">
                            <button
                              type="button"
                              className="kanban-worker-stat kanban-worker-stat-action"
                              onClick={() => handleOpenDashboardEmployeeHistory(worker.id)}
                              title={`查看 ${worker.name} 已处理任务`}
                            >
                              <div className="kanban-worker-stat-label">已处理任务</div>
                              <div className="kanban-worker-stat-value">{worker.historyCount} 条</div>
                            </button>
                            <div className="kanban-worker-stat">
                              <div className="kanban-worker-stat-label">工作状态</div>
                              <div className="kanban-worker-stat-value">{worker.workStatus}</div>
                            </div>
                          </div>
                          <div className="kanban-card-footer">
                            <span
                              className="kanban-card-tag"
                              style={{ background: runtimeBg, color: runtimeTextColor }}
                            >
                              {runtimeLabel}
                            </span>
                            <button
                              type="button"
                              className="kanban-card-time kanban-card-link-btn"
                              onClick={() => handleOpenTaskEmployeeChat(worker.id, latestSession)}
                              title={`进入 ${worker.name} 对话`}
                            >
                              点击进入对话
                            </button>
                          </div>
                        </div>
                      );
                    })
                  ) : (
                    <div className="kanban-empty-card">
                      <div className="kanban-card-title">暂无匹配的数字员工</div>
                      <div className="kanban-card-desc">请切换筛选条件，查看其他数字员工状态。</div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="kanban-board">
                  {filteredDashboardWorkColumns.length ? (
                    filteredDashboardWorkColumns.map((column) => (
                      <section key={`kanban-column-${column.id}`} className="kanban-col">
                        <div className="kanban-col-header">
                          <div className="kanban-col-dot" style={{ background: column.dot, color: column.dot }} />
                          <div className="kanban-col-title">{column.title}</div>
                          <div className="kanban-col-count">{column.cards.length}</div>
                        </div>
                        <div className="kanban-col-body">
                          {column.cards.map((card) => (
                            <button
                              key={card.id}
                              type="button"
                              className="kanban-card work-card"
                              onClick={() => handleOpenTaskEmployeeChat(card.ownerEmployeeIds[0])}
                            >
                              <span
                                className="kanban-card-stripe"
                                style={{ background: card.ownerColor }}
                                aria-hidden="true"
                              />
                              <div className="kanban-card-title">{card.title}</div>
                              <div className="kanban-card-desc">{card.description}</div>
                              <div className="kanban-emp divided">
                                <DigitalEmployeeAvatar
                                  employee={getEmployeeById(card.ownerEmployeeIds[0])}
                                  className="kanban-emp-avatar small"
                                />
                                <div className="kanban-emp-name">{card.ownerLabel}</div>
                              </div>
                              {typeof card.progress === "number" ? (
                                <div className="kanban-progress">
                                  <div className="kanban-progress-bar">
                                    <div
                                      className="kanban-progress-fill"
                                      style={{
                                        width: `${card.progress}%`,
                                        background: `linear-gradient(90deg, ${card.ownerColor}, ${card.ownerColor}cc)`,
                                      }}
                                    />
                                  </div>
                                  <div className="kanban-progress-label">
                                    <span>进度</span>
                                    <span style={{ color: card.ownerColor, fontWeight: 600 }}>
                                      {card.progress}%
                                    </span>
                                  </div>
                                </div>
                              ) : null}
                              {typeof card.score === "number" ? (
                                <div className="kanban-score" aria-label={`评分 ${card.score}`}>
                                  {Array.from({ length: 5 }, (_, index) => (
                                    <span
                                      key={`${card.id}-score-${index}`}
                                      className={card.score >= index + 1 ? "star filled" : "star"}
                                    >
                                      ★
                                    </span>
                                  ))}
                                  <span className="kanban-score-val">{card.score}</span>
                                </div>
                              ) : null}
                              <div className="kanban-card-footer">
                                <span
                                  className="kanban-card-tag"
                                  style={{ background: card.tagBg, color: card.tagColor }}
                                >
                                  {card.label}
                                </span>
                                <span className={card.isUrgent ? "kanban-card-time urgent" : "kanban-card-time"}>
                                  {card.timeText}
                                </span>
                              </div>
                            </button>
                          ))}
                        </div>
                      </section>
                    ))
                  ) : (
                    <div className="kanban-empty-column">
                      <div className="kanban-col-header">
                        <div className="kanban-col-dot" style={{ background: "#94a3b8", color: "#94a3b8" }} />
                        <div className="kanban-col-title">当前筛选结果</div>
                        <div className="kanban-col-count">0</div>
                      </div>
                      <div className="kanban-col-body">
                        <div className="kanban-empty-card">
                          <div className="kanban-card-title">暂无匹配内容</div>
                          <div className="kanban-card-desc">请切换筛选条件，查看其他工作任务状态。</div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : null}

          {currentView === "tasks" ? (
            <CronJobsPanel />
          ) : null}

          {currentView === "chat" ? (
            <div className={isPortalHomeChat ? "chat-container portal-home-chat" : "chat-container"}>
              {showPortalHomeHero ? (
                <div className="portal-home-stage">
                  <div className="portal-home-toolbar">
                    {renderAlertBell()}
                    <button
                      type="button"
                      className="ops-board-theme-toggle portal-home-theme-toggle"
                      onClick={() => setPageTheme((value) => (value === "light" ? "dark" : "light"))}
                      aria-label="切换整页主题"
                      title="切换整页主题"
                    >
                      {themeToggleIcon}
                    </button>
                    <button
                      type="button"
                      className="ops-board-theme-toggle portal-home-traditional-toggle"
                      onClick={handleSwitchTraditionalView}
                      aria-label="切换传统视图"
                      title="切换传统视图"
                    >
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                      >
                        <rect x="3" y="3" width="7" height="7" />
                        <rect x="14" y="3" width="7" height="7" />
                        <rect x="3" y="14" width="7" height="7" />
                        <rect x="14" y="14" width="7" height="7" />
                      </svg>
                      <span>切换传统视图</span>
                    </button>
                  </div>
                  <div className="portal-home-hero">
                    <div className="portal-home-orbit">
                      <span className="portal-home-orbit-ring outer" />
                      <span className="portal-home-orbit-ring inner" />
                      <span className="portal-home-orbit-core">
                        <img src={portalLogo} alt="智观 AI" className="portal-home-orbit-image" />
                      </span>
                    </div>
                    <h2>智观 AI</h2>
                    <p>以对话方式发起运维协同</p>
                  </div>

                  <div className="portal-employee-switcher compact stage">
                    <div className="portal-employee-switcher-grid compact stage">
                      {digitalEmployees.map((employee) => (
                        <button
                          key={`compact-stage-${employee.id}`}
                          type="button"
                          className="portal-employee-pill compact stage"
                          onClick={() => prefillEmployeeMention(employee)}
                        >
                          <DigitalEmployeeAvatar
                            employee={employee}
                            className="portal-employee-pill-avatar compact"
                          />
                          <span className="portal-employee-pill-copy compact">
                            <strong>{employee.name}</strong>
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="portal-home-composer-card">
                    <textarea
                      ref={homeComposerRef}
                      value={inputMessage}
                      disabled={isCreatingChat || isStreaming}
                      onBlur={() => window.setTimeout(() => setInputCursor(null), 120)}
                      onClick={handleInputSelection}
                      onChange={(event) => {
                        setInputMessage(event.target.value);
                        setInputCursor(event.target.selectionStart ?? event.target.value.length);
                      }}
                      onKeyDown={(event) => handleComposerKeyDown(event, { multiline: true })}
                      onKeyUp={handleInputSelection}
                      placeholder="输入您的问题..."
                    />
                    {mentionSuggestions.length ? (
                      <div className="mention-suggestions home">
                        {mentionSuggestions.map((item, index) => (
                          <button
                            key={`home-mention-${item.employee.id}`}
                            type="button"
                            className={
                              index === mentionActiveIndex
                                ? "mention-suggestion active"
                                : "mention-suggestion"
                            }
                            onMouseDown={(event) => {
                              event.preventDefault();
                              applyMentionSuggestion(item.employee.name);
                            }}
                          >
                            <DigitalEmployeeAvatar
                              employee={item.employee}
                              className="mention-suggestion-avatar"
                            />
                            <span className="mention-suggestion-copy">
                              <strong>{item.employee.name}</strong>
                              <small>{item.employee.desc}</small>
                            </span>
                          </button>
                        ))}
                      </div>
                    ) : null}
                    <div className="portal-home-composer-footer">
                      <div className="portal-home-quick-actions">
                        {safeQuickCommands.map((command) => (
                          <button
                            key={`home-${command}`}
                            className="portal-home-quick-action"
                            onClick={() => void handleSendMessage(command)}
                            disabled={isCreatingChat || isStreaming}
                          >
                            {command}
                          </button>
                        ))}
                      </div>
                      <button
                        className={
                          isCreatingChat
                            ? "send-btn disabled"
                            : isStreaming
                              ? "send-btn stop-mode"
                              : "send-btn"
                        }
                        onClick={() => {
                          if (isStreaming) {
                            stopActiveStream(true);
                            return;
                          }
                          void handleSendMessage();
                        }}
                        disabled={isCreatingChat}
                        aria-label={isStreaming ? "停止聊天" : "发送消息"}
                      >
                        {isStreaming ? (
                          <span className="send-btn-stop-icon" aria-hidden="true" />
                        ) : (
                          <i className="fas fa-paper-plane" />
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                <>
                  {!isPortalHomeChat ? (
                  <div className="chat-header">
                    <div className="chat-header-main">
                      <div className="chat-header-copy">
                        <strong>
                          {isAlarmWorkbenchMode
                            ? `${currentEmployee.name} - 告警工单处置`
                            : `${currentEmployee.name} - 智能服务`}
                        </strong>
                        <span>支持历史追溯、模型切换与专属能力调用</span>
                      </div>
                      {!isRemoteEmployee && isAlarmWorkbenchMode ? (
                        <span
                          className={
                            isAlarmWorkbenchMode
                              ? "chat-status-pill alert"
                              : isStreaming || currentChatStatus === "running"
                                ? "chat-status-pill running"
                                : "chat-status-pill"
                          }
                        >
                          {isAlarmWorkbenchMode
                            ? "告警触发"
                            : isCreatingChat
                              ? "创建中"
                              : isStreaming || currentChatStatus === "running"
                                ? "对话中"
                                : currentChatId
                                  ? "历史可追溯"
                                  : "等待发起"}
                        </span>
                      ) : null}
                    </div>
                    <div
                      className={
                        isAlarmWorkbenchMode ? "chat-capabilities alarm-mode" : "chat-capabilities"
                      }
                    >
                      {isAlarmWorkbenchMode ? (
                        <>
                          {showModelSelector ? (
                            <ChatModelSelector
                              activeModelLabel={activeModelLabel}
                              activeProviderId={activeProviderId}
                              activeModelId={activeModelId}
                              eligibleProviders={eligibleProviders}
                              loading={modelsLoading}
                              switching={modelsSwitching}
                              disabled={isCreatingChat || isStreaming}
                              notice={modelNotice}
                              onSelectModel={handleSelectModel}
                              onOpenConfig={openModelConfig}
                            />
                          ) : null}
                          <>
                            <button className="history-btn" onClick={() => void handleOpenHistory()}>
                              <i className="fas fa-history" /> 已处理任务
                            </button>
                            <button className="history-btn new-chat-btn" onClick={handleStartNewConversation}>
                              <i className="fas fa-plus" /> 新对话
                            </button>
                          </>
                          <span className="capability-tag active static-tag">
                            <i className="fas fa-file-lines" /> 工单视图
                          </span>
                        </>
                      ) : (
                        <>
                          {showModelSelector ? (
                            <ChatModelSelector
                              activeModelLabel={activeModelLabel}
                              activeProviderId={activeProviderId}
                              activeModelId={activeModelId}
                              eligibleProviders={eligibleProviders}
                              loading={modelsLoading}
                              switching={modelsSwitching}
                              disabled={isCreatingChat || isStreaming}
                              notice={modelNotice}
                              onSelectModel={handleSelectModel}
                              onOpenConfig={openModelConfig}
                            />
                          ) : null}
                          <>
                            <button className="history-btn" onClick={() => void handleOpenHistory()}>
                              <i className="fas fa-history" /> 已处理任务
                            </button>
                            <button className="history-btn new-chat-btn" onClick={handleStartNewConversation}>
                              <i className="fas fa-plus" /> 新对话
                            </button>
                          </>
                          <span className="capability-tag active static-tag">
                            <i className="fas fa-file-lines" /> 工单视图
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                  ) : null}

                  <>
                    <div className="chat-messages">
                      {safeMessages.map((message) => (
                        <ChatMessageItem
                          key={message.id}
                          currentEmployee={currentEmployee}
                          isStreamingMessage={
                            Boolean(message.streaming) ||
                            (isStreaming && message.id === activeAssistantMessageIdRef.current)
                          }
                          message={message}
                          onDisposalAction={handleAlarmDisposalOperationRequest}
                          onTicketAction={handleAlarmWorkbenchTicketAction}
                          onTicketRefresh={() => void loadAlarmWorkorders()}
                          ticketActionNotice={ticketActionNotice}
                        />
                      ))}
                      <div ref={messagesEndRef} />
                    </div>

                    {!isAlarmWorkbenchMode ? (
                      <div className="quick-commands">
                        <div className="capabilities-row">
                          {safeCapabilities.map((item) => (
                            <span key={item} className="capability-label">
                              {item}
                            </span>
                          ))}
                        </div>
                        <div className="quick-cmd-row">
                          {safeQuickCommands.map((command) => (
                            <button
                              key={command}
                              className="quick-cmd"
                              onClick={() => void handleSendMessage(command)}
                              disabled={isCreatingChat || isStreaming}
                            >
                              <i className="fas fa-bolt" />
                              {command}
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    <div className="input-area">
                      <div className="input-hint-row">
                        <span>
                        输入自然语言即可开始协同办公。
                        </span>
                      </div>
                      <div className="input-wrapper">
                        <div className={isCreatingChat ? "input-box disabled" : "input-box"}>
                          <i className="fas fa-comment-dots" />
                          <input
                            ref={chatInputRef}
                            type="text"
                            value={inputMessage}
                            disabled={isCreatingChat || isStreaming}
                            onBlur={() => window.setTimeout(() => setInputCursor(null), 120)}
                            onClick={handleInputSelection}
                            onChange={(event) => {
                              setInputMessage(event.target.value);
                              setInputCursor(event.target.selectionStart ?? event.target.value.length);
                            }}
                            onKeyDown={(event) => handleComposerKeyDown(event)}
                            onKeyUp={handleInputSelection}
                            placeholder={`向 ${currentEmployee.name} 描述您的需求...`}
                          />
                        </div>
                        {mentionSuggestions.length ? (
                          <div className="mention-suggestions">
                            {mentionSuggestions.map((item, index) => (
                              <button
                                key={`mention-${item.employee.id}`}
                                type="button"
                                className={
                                  index === mentionActiveIndex
                                    ? "mention-suggestion active"
                                    : "mention-suggestion"
                                }
                                onMouseDown={(event) => {
                                  event.preventDefault();
                                  applyMentionSuggestion(item.employee.name);
                                }}
                              >
                                <DigitalEmployeeAvatar
                                  employee={item.employee}
                                  className="mention-suggestion-avatar"
                                />
                                <span className="mention-suggestion-copy">
                                  <strong>{item.employee.name}</strong>
                                  <small>{item.employee.desc}</small>
                                </span>
                              </button>
                            ))}
                          </div>
                        ) : null}
                        <button
                          className={
                            isCreatingChat
                              ? "send-btn disabled"
                              : isStreaming
                                ? "send-btn stop-mode"
                                : "send-btn"
                          }
                          onClick={() => {
                            if (isStreaming) {
                              stopActiveStream(true);
                              return;
                            }
                            void handleSendMessage();
                          }}
                          disabled={isCreatingChat}
                          aria-label={isStreaming ? "停止聊天" : "发送消息"}
                        >
                          {isStreaming ? (
                            <span className="send-btn-stop-icon" aria-hidden="true" />
                          ) : (
                            <i className="fas fa-paper-plane" />
                          )}
                        </button>
                      </div>
                    </div>
                  </>
                </>
              )}
            </div>
          ) : null}
            </>
          )}
        </div>
      </div>

      {alertPopup}

      {dashboardHistoryVisible ? (
        <div className="history-modal show" onClick={() => setDashboardHistoryVisible(false)}>
          <div className="history-content" onClick={(event) => event.stopPropagation()}>
            <div className="history-header">
              <h3>
                <i className="fas fa-history" /> {dashboardHistoryEmployee?.name || "数字员工"}已处理任务
              </h3>
              <button className="history-close" onClick={() => setDashboardHistoryVisible(false)}>
                <i className="fas fa-times" />
              </button>
            </div>
            <div className="history-body">
              {dashboardHistoryLoading ? (
                <div className="history-empty">
                  <i className="fas fa-spinner fa-spin" />
                  <p>正在加载已处理任务...</p>
                </div>
              ) : dashboardHistoryError ? (
                <div className="history-empty">
                  <i className="fas fa-triangle-exclamation" />
                  <p>{dashboardHistoryError}</p>
                </div>
              ) : dashboardHistorySessions.length ? (
                <div className="history-timeline">
                  {dashboardHistorySessions.map((session) => (
                    <div key={session.id} className={`history-item ${session.status || ""}`.trim()}>
                      <button
                        type="button"
                        className="history-item-main"
                        onClick={() => handleSelectDashboardHistory(dashboardHistoryEmployeeId, session)}
                      >
                        <div className="history-time">
                          {new Date(
                            session.updatedAt || session.createdAt || new Date().toISOString(),
                          ).toLocaleString("zh-CN")}
                        </div>
                        <div className="history-title">{session.title}</div>
                        {session.detail ? <div className="history-detail">{session.detail}</div> : null}
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="history-empty">
                  <i className="fas fa-clock-rotate-left" />
                  <p>当前暂无已处理任务</p>
                </div>
              )}
            </div>
          </div>
        </div>
      ) : null}

      {historyVisible ? (
        <div className="history-modal show" onClick={() => setHistoryVisible(false)}>
          <div className="history-content" onClick={(event) => event.stopPropagation()}>
            <div className="history-header">
              <h3>
                <i className="fas fa-history" /> 已处理任务
              </h3>
              <button className="history-close" onClick={() => setHistoryVisible(false)}>
                <i className="fas fa-times" />
              </button>
            </div>
            <div className="history-body">
              {historyActionError ? (
                <div className="history-inline-error">
                  <i className="fas fa-circle-exclamation" />
                  <span>{historyActionError}</span>
                </div>
              ) : null}
              {historyLoading ? (
                <div className="history-empty">
                  <i className="fas fa-spinner fa-spin" />
                  <p>正在加载已处理任务...</p>
                </div>
              ) : historyError ? (
                <div className="history-empty">
                  <i className="fas fa-triangle-exclamation" />
                  <p>{historyError}</p>
                </div>
              ) : sessionList.length ? (
                <div className="history-timeline">
                  {sessionList.map((session) => {
                    const isActiveSession =
                      session.id === (isRemoteEmployee ? currentChatId : currentSessionId);
                    const isEditingSession = historyEditingId === session.id;
                    const isBusySession = historyActionSessionId === session.id;
                    const isLockedRemoteSession =
                      isRemoteEmployee &&
                      isActiveSession &&
                      (isStreaming || currentChatStatus === "running");

                    return (
                      <div
                        key={session.id}
                        className={
                          isActiveSession
                            ? `history-item ${session.status || ""} active-session`.trim()
                            : `history-item ${session.status || ""}`.trim()
                        }
                      >
                        <button
                          type="button"
                          className="history-item-main"
                          onClick={() => void handleSelectHistory(session)}
                        >
                          <div className="history-time">
                            {new Date(
                              session.updatedAt || session.createdAt || new Date().toISOString(),
                            ).toLocaleString("zh-CN")}
                          </div>
                          {isEditingSession ? (
                            <input
                              autoFocus
                              className="history-title-input"
                              value={historyDraftTitle}
                              onChange={(event) => setHistoryDraftTitle(event.target.value)}
                              onClick={(event) => event.stopPropagation()}
                              onKeyDown={(event) => {
                                if (event.key === "Enter") {
                                  event.preventDefault();
                                  void handleSubmitHistoryRename(session);
                                }
                                if (event.key === "Escape") {
                                  event.preventDefault();
                                  handleCancelHistoryRename();
                                }
                              }}
                              placeholder="请输入会话名称"
                            />
                          ) : (
                            <div className="history-title">{session.title}</div>
                          )}
                        </button>
                        <div className="history-item-actions">
                          {isEditingSession ? (
                            <>
                              <button
                                type="button"
                                className="history-item-action confirm"
                                onClick={() => void handleSubmitHistoryRename(session)}
                                disabled={isBusySession}
                                title="保存会话名称"
                              >
                                <i className={isBusySession ? "fas fa-spinner fa-spin" : "fas fa-check"} />
                              </button>
                              <button
                                type="button"
                                className="history-item-action"
                                onClick={handleCancelHistoryRename}
                                disabled={isBusySession}
                                title="取消编辑"
                              >
                                <i className="fas fa-xmark" />
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                type="button"
                                className="history-item-action"
                                onClick={() => handleStartHistoryRename(session)}
                                disabled={isBusySession || isLockedRemoteSession}
                                title={isLockedRemoteSession ? "当前会话处理中，暂不可编辑" : "编辑会话名称"}
                              >
                                <i className="fas fa-pen" />
                              </button>
                              <button
                                type="button"
                                className="history-item-action delete"
                                onClick={() => void handleDeleteHistorySession(session)}
                                disabled={isBusySession || isLockedRemoteSession}
                                title={isLockedRemoteSession ? "当前会话处理中，暂不可删除" : "删除会话"}
                              >
                                <i className={isBusySession ? "fas fa-spinner fa-spin" : "fas fa-trash-can"} />
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="history-empty">
                  <i className="fas fa-clock-rotate-left" />
                  <p>当前暂无已处理任务</p>
                </div>
              )}
            </div>
          </div>
        </div>
      ) : null}

      {executionVisible ? (
        <div className="history-modal show" onClick={() => setExecutionVisible(false)}>
          <div className="history-content" onClick={(event) => event.stopPropagation()}>
            <div className="history-header">
              <h3>
                <i className="fas fa-history" /> {executionTitle}
              </h3>
              <button className="history-close" onClick={() => setExecutionVisible(false)}>
                <i className="fas fa-times" />
              </button>
            </div>
            <div className="history-body">
              <div className="history-timeline">
                {safeExecutionList.map((item) => (
                  <div key={item.id} className={`history-item ${item.status}`}>
                    <div className="history-time">{item.time}</div>
                    <div className="history-title">{item.title}</div>
                    <div className="history-detail">{item.detail}</div>
                    <div className="history-agent-tag">
                      <i className={`fas ${item.agentIcon}`} />
                      {item.agent}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {pendingDisposalAction ? (
        <div className="history-modal show" onClick={handleCancelDisposalAction}>
          <div
            className="history-content disposal-confirm-content"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="history-header">
              <h3>
                <i className="fas fa-triangle-exclamation" /> 确认执行慢SQL处置
              </h3>
              <button className="history-close" onClick={handleCancelDisposalAction}>
                <i className="fas fa-times" />
              </button>
            </div>
            <div className="history-body disposal-confirm-body">
              <div className="disposal-confirm-alert">
                即将对根因工单
                <strong>{` ${pendingDisposalAction.operation.rootCauseWorkorderNo} `}</strong>
                执行慢SQL终止动作。该动作会中断当前异常会话，适合用于演示环境串联处置流程。
              </div>
              <div className="disposal-confirm-grid">
                <div>
                  <span>来源工单</span>
                  <strong>{pendingDisposalAction.operation.sourceWorkorderNo}</strong>
                </div>
                <div>
                  <span>根因工单</span>
                  <strong>{pendingDisposalAction.operation.rootCauseWorkorderNo}</strong>
                </div>
                <div>
                  <span>SQL_ID</span>
                  <strong>{pendingDisposalAction.operation.sqlId}</strong>
                </div>
                <div>
                  <span>会话ID</span>
                  <strong>{pendingDisposalAction.operation.sessionId}</strong>
                </div>
                <div>
                  <span>设备</span>
                  <strong>{pendingDisposalAction.operation.deviceName}</strong>
                </div>
                <div>
                  <span>实例/IP</span>
                  <strong>{`${pendingDisposalAction.operation.locateName} / ${pendingDisposalAction.operation.manageIp}`}</strong>
                </div>
                <div>
                  <span>处置对象</span>
                  <strong>
                    {pendingDisposalAction.operation.targetSummary ||
                      "数据库核心业务慢 SQL 会话"}
                  </strong>
                </div>
              </div>
              <div className="disposal-confirm-actions">
                <button
                  className="alarm-workorder-action"
                  disabled={isSubmittingDisposalAction}
                  onClick={handleCancelDisposalAction}
                >
                  取消
                </button>
                <button
                  className="alarm-workorder-action primary"
                  disabled={isSubmittingDisposalAction}
                  onClick={() => void handleConfirmDisposalAction()}
                >
                  <i
                    className={`fas ${
                      isSubmittingDisposalAction ? "fa-spinner fa-spin" : "fa-bolt"
                    }`}
                  />{" "}
                  {isSubmittingDisposalAction ? "执行中..." : "确认执行"}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
      </div>
    </DigitalEmployeeErrorBoundary>
  );
}
