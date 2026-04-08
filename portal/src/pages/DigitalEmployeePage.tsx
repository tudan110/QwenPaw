import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import {
  digitalEmployees,
  employeeResults,
  employeeWorkflows,
  executionHistory,
  getEmployeeById,
  operationsBoardColumns,
} from "../data/portalData";
import {
  createConversationSession,
  loadConversationStore,
  saveConversationStore,
} from "../lib/conversationStore";
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
import { TaskViewPanel } from "./digital-employee/taskViewPanel";
import { TokenUsagePanel } from "./digital-employee/tokenUsagePanel";
import {
  ALARM_WORKORDER_ENTRY,
  buildPortalSectionPath,
  buildEmployeePagePath,
  buildSessionTitle,
  createAgentMessage,
  createAlarmWorkorderMessage,
  createUserMessage,
  createWelcomeMessage,
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
import "./digital-employee.css";

const capabilityOptions = [
  { id: "scan", label: "快速发现", icon: "fa-magnifying-glass" },
  { id: "auto", label: "自动化", icon: "fa-wand-magic-sparkles" },
  { id: "analyze", label: "智能分析", icon: "fa-chart-pie" },
] as const;

const sidebarEmployeePriority = ["query", "fault"] as const;

const REMOTE_AGENT_IDS: Record<string, string> = {
  fault: "fault",
  query: "query",
};

const PAGE_THEME_STORAGE_KEY = "portal-digital-employee-theme";

const operationsBoardDots = {
  pending: "pending",
  running: "running",
  completed: "completed",
  closed: "closed",
} as const;

type SessionRecord = {
  id: string;
  title: string;
  createdAt?: string;
  updatedAt?: string;
  messages?: any[];
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
  const selectedEmployee = useMemo(() => {
    if (!employeeId) {
      return null;
    }
    return digitalEmployees.find((item) => item.id === employeeId) || null;
  }, [employeeId]);
  const defaultEmployee = useMemo(
    () => getEmployeeById(sidebarEmployeePriority[0]) || digitalEmployees[0],
    [],
  );
  const currentEmployee = selectedEmployee || defaultEmployee;
  const routeSection = forcedSection || null;
  const remoteAgentId = selectedEmployee ? REMOTE_AGENT_IDS[selectedEmployee.id] : null;
  const isRemoteEmployee = Boolean(remoteAgentId);
  const routeSearchParams = useMemo(
    () => new URLSearchParams(location.search),
    [location.search],
  );
  const currentEntry = routeSearchParams.get("entry");
  const currentView = parsePortalView(routeSection ?? routeSearchParams.get("view"));
  const activeAdvancedPanel = parsePortalAdvancedPanel(
    routeSection ?? routeSearchParams.get("panel"),
  );
  const isAlarmWorkbenchMode = Boolean(
    selectedEmployee?.id === "fault" && currentEntry === ALARM_WORKORDER_ENTRY,
  );

  const [activeCapability, setActiveCapability] =
    useState<(typeof capabilityOptions)[number]["id"]>("scan");
  const [inputMessage, setInputMessage] = useState("");
  const [messages, setMessages] = useState<any[]>([]);
  const [conversationStore, setConversationStore] = useState<ConversationStoreState>(
    () => loadConversationStore() as ConversationStoreState,
  );
  const [executionVisible, setExecutionVisible] = useState(false);
  const [executionTitle, setExecutionTitle] = useState("执行历史");
  const [executionList, setExecutionList] = useState(executionHistory);
  const [pageTheme, setPageTheme] = useState<"light" | "dark">(loadPageTheme);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const {
    currentSessionId,
    setCurrentSessionId,
    currentChatId,
    setCurrentChatId,
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

  const navigateToEmployeePage = (
    employee: any,
    options: {
      entry?: string | null;
      view?: PortalView;
      panel?: PortalAdvancedPanel | null;
      replace?: boolean;
    } = {},
  ) => {
    navigate(
      buildEmployeePagePath(employee, {
        entry: options.entry,
        view: options.view,
        panel: options.panel,
      }),
      options.replace ? { replace: true } : undefined,
    );
  };

  const updateCurrentEmployeeRoute = (
    options: {
      entry?: string | null;
      view?: PortalView;
      panel?: PortalAdvancedPanel | null;
      replace?: boolean;
    } = {},
  ) => {
    if (!currentEmployee) {
      return;
    }

    navigateToEmployeePage(currentEmployee, {
      entry: options.entry ?? currentEntry,
      view: options.view ?? currentView,
      panel: options.panel === undefined ? activeAdvancedPanel : options.panel,
      replace: options.replace,
    });
  };

  const openModelConfig = () => {
    navigate(buildPortalSectionPath("model-config"));
  };

  useEffect(() => {
    if (!currentEmployee) {
      return;
    }

    if (employeeId && !selectedEmployee) {
      navigate("/", { replace: true });
      return;
    }

    if (routeSearchParams.has("view") || routeSearchParams.has("panel")) {
      navigateToEmployeePage(currentEmployee, {
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
  ]);

  useEffect(() => {
    if (!currentEmployee) {
      return;
    }

    setActiveCapability("scan");
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
      const initialMessages = [createWelcomeMessage(currentEmployee)];
      const nextSession = createConversationSession(currentEmployee, initialMessages);

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

      setCurrentSessionId(nextSession.id);
      setMessages(initialMessages);
      return;
    }

    resetRemoteState({
      initialMessages: [createWelcomeMessage(currentEmployee)],
    });
  }, [
    currentEmployee,
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

  const totalTasks = useMemo(
    () => digitalEmployees.reduce((sum, employee) => sum + employee.tasks, 0),
    [],
  );
  const runningTasks = useMemo(
    () =>
      digitalEmployees.filter((employee) => employee.status === "running").length,
    [],
  );
  const sidebarEmployees = useMemo(() => {
    const priorityIds = new Set(sidebarEmployeePriority);
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

  const safeMessages = ensureObjectArray(messages);
  const safeExecutionList = ensureObjectArray<ExecutionRecord>(executionList);
  const safeCapabilities = ensureStringArray(currentEmployee?.capabilities);
  const safeQuickCommands = ensureStringArray(currentEmployee?.quickCommands);
  const showModelSelector = currentView === "chat";
  const isModelConfigMode = activeAdvancedPanel === "model-config";
  const isTokenUsageMode = activeAdvancedPanel === "token-usage";

  const sessionList = (
    isRemoteEmployee
      ? remoteSessions
      : ensureSessionRecords(conversationStore[currentEmployee?.id || ""])
  ) as SessionRecord[];

  const updateMessagesAndStore = (
    nextMessages: any[],
    nextSessionId: string = currentSessionId,
  ) => {
    setMessages(nextMessages);

    if (!currentEmployee || isRemoteEmployee) {
      return;
    }

    setConversationStore((prevStore) => {
      const previousSessions = ensureSessionRecords(prevStore[currentEmployee.id]);
      const nextStore: ConversationStoreState = {
        ...prevStore,
        [currentEmployee.id]: previousSessions.map((session) =>
          session.id === nextSessionId
            ? {
                ...session,
                messages: nextMessages,
                updatedAt: new Date().toISOString(),
                title: buildSessionTitle(currentEmployee.name, nextMessages),
              }
            : session,
        ),
      };
      saveConversationStore(nextStore);
      return nextStore;
    });
  };

  const handleSendMessage = async (preset = "") => {
    const content = (preset || inputMessage).trim();
    if (!content || !currentEmployee) {
      return;
    }

    if (!preset) {
      setInputMessage("");
    }

    if (isRemoteEmployee) {
      await handleRemoteSendMessage(content);
      return;
    }

    const userMessage = createUserMessage(content);
    const workflow =
      employeeWorkflows[currentEmployee.id as keyof typeof employeeWorkflows] || [];
    const result =
      employeeResults[currentEmployee.id as keyof typeof employeeResults] || null;
    const processingMessage = {
      ...createAgentMessage(currentEmployee, {
        id: `agent-${Date.now()}`,
        content: "收到！我正在为您处理...",
      }),
      workflow: [...workflow],
      currentStep: 0,
      workflowDone: false,
      stepTimes: [] as string[],
      result: null,
    };

    const initialQueue = [...messages, userMessage, processingMessage];
    updateMessagesAndStore(initialQueue);

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
            updateMessagesAndStore(nextMessages);
          }, 0);
        }

        return nextMessages;
      });
      step += 1;
    }, 800);
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

  const handleOpenTaskEmployeeChat = (employeeId: string) => {
    const employee = getEmployeeById(employeeId);
    if (!employee) {
      return;
    }
    navigateToEmployeePage(employee, {
      view: "chat",
      panel: null,
    });
  };

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
          <div className="logo">
            <div className="logo-icon">
              <i className="fas fa-brain" />
            </div>
            <div className="logo-text">
              <h1>{portalAppTitle}</h1>
              <span>智能 · 高效 · 自动化</span>
            </div>
          </div>

          <div className="view-tabs">
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
            <button
              className={currentView === "tasks" ? "view-tab active" : "view-tab"}
              onClick={() => {
                updateCurrentEmployeeRoute({
                  view: "tasks",
                  panel: null,
                });
              }}
            >
              <i className="fas fa-list-check" />
              <span>任务</span>
            </button>
          </div>

          <div className="agents-title">
            <i className="fas fa-users" />
            数字员工矩阵
          </div>

          <div className="agent-list">
            {sidebarEmployees.map((employee) => (
              <button
                key={employee.id}
                className={
                  employee.id === selectedEmployee?.id ? "agent-card active" : "agent-card"
                }
                onClick={() => {
                  navigateToEmployeePage(employee, {
                    view: "chat",
                    panel: null,
                  });
                }}
              >
                <span
                  className={
                    employee.urgent
                      ? "status-badge urgent"
                      : employee.status === "running"
                        ? "status-badge running"
                        : "status-badge stopped"
                  }
                >
                  {employee.urgent
                    ? "紧急"
                    : employee.status === "running"
                      ? "运行中"
                      : "已停止"}
                </span>

                <div className="agent-header">
                  <DigitalEmployeeAvatar employee={employee} />
                  <div className="agent-info">
                    <h3>{employee.name}</h3>
                    <p>{employee.desc}</p>
                  </div>
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
              </button>
            ))}
          </div>

          <AdvancedModelEntry
            activeModelLabel={activeModelLabel}
            activeProviderName={activeProviderName}
            isActive={isModelConfigMode}
            isTokenUsageActive={isTokenUsageMode}
            onOpenConfig={openModelConfig}
            onOpenTokenUsage={() =>
              updateCurrentEmployeeRoute({
                panel: "token-usage",
              })
            }
          />
        </div>

        <div
          className={
            isModelConfigMode || isTokenUsageMode
              ? "main-content advanced-page-mode"
              : currentView === "chat"
                ? "main-content"
                : currentView === "tasks"
                  ? "main-content card-mode task-page-mode"
                  : "main-content card-mode"
          }
        >
          <button
            type="button"
            className="ops-board-theme-toggle portal-global-theme-toggle"
            onClick={() => setPageTheme((value) => (value === "light" ? "dark" : "light"))}
            aria-label="切换整页主题"
            title="切换整页主题"
          >
            <i className={`fas ${pageTheme === "light" ? "fa-moon" : "fa-sun"}`} />
          </button>
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
          ) : (
            <>
          <div className="top-bar">
            <div className="active-agent-title">
              <div className="active-agent-avatar">
                <i
                  className={`fas ${
                    currentView === "dashboard"
                      ? "fa-chart-pie"
                      : currentView === "tasks"
                        ? "fa-list-check"
                        : currentEmployee.icon
                  }`}
                />
              </div>
              <div className="active-agent-info">
                <h2>
                  {currentView === "dashboard"
                    ? "数字员工看板"
                    : currentView === "tasks"
                      ? "每日任务"
                      : currentEmployee.name}
                </h2>
                <span>
                  {currentView === "dashboard"
                    ? "查看整体运营状态和统计"
                    : currentView === "tasks"
                      ? "查看和管理每日任务"
                      : isAlarmWorkbenchMode
                        ? "告警触发后自动生成的待处置工单视图"
                        : currentEmployee.desc}
                </span>
              </div>
            </div>
            <div className="top-bar-actions">
              {currentView === "chat" ? (
                <div className="top-bar-stats">
                  <div className="top-stat">
                    <div className="top-stat-value">{totalTasks}</div>
                    <div className="top-stat-label">总任务数</div>
                  </div>
                  <div className="top-stat">
                    <div className="top-stat-value">{runningTasks}</div>
                    <div className="top-stat-label">进行中</div>
                  </div>
                  <div className="top-stat">
                    <div className="top-stat-value">45s</div>
                    <div className="top-stat-label">平均耗时</div>
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          {currentView === "dashboard" ? (
            <div className="ops-board-shell">
              <div className="ops-board-header">
                <div className="ops-board-title-group">
                  <h3 className="ops-board-title">
                    运维看板
                    <span>实时任务概览</span>
                  </h3>
                </div>
              </div>
              <div className="ops-board-columns">
                {operationsBoardColumns.map((column) => (
                  <section key={column.id} className={`ops-column ops-column-${column.id}`}>
                    <div className="ops-column-header">
                      <div className="ops-column-title">
                        <span
                          className={`ops-column-dot ${operationsBoardDots[column.id]}`}
                        />
                        <span>{column.title}</span>
                      </div>
                      <span className="ops-column-count">{column.items.length}</span>
                    </div>
                    <div className="ops-column-list">
                      {column.items.map((item) => (
                        <article
                          key={item.id}
                          className={
                            typeof item.progress === "number"
                              ? `ops-task-card tone-${item.tone} has-progress`
                              : `ops-task-card tone-${item.tone}`
                          }
                        >
                          <div
                            className="ops-task-stripe"
                            style={{ background: item.ownerColor }}
                            aria-hidden="true"
                          />
                          <div className="ops-task-owner-row">
                            <DigitalEmployeeAvatar
                              employee={getEmployeeById(item.ownerEmployeeIds[0])}
                              className="ops-owner-avatar"
                            />
                            <span className="ops-task-owner-text">{item.ownerLabel}</span>
                          </div>
                          <h4 className="ops-task-title">{item.title}</h4>
                          <p className="ops-task-desc">{item.description}</p>
                          {typeof item.progress === "number" ? (
                            <>
                            <div className="ops-progress-block">
                              <div className="ops-progress-bar">
                                <span
                                  style={{
                                    width: `${item.progress}%`,
                                    background: `linear-gradient(90deg, ${item.ownerColor}, ${item.ownerColor}cc)`,
                                  }}
                                />
                              </div>
                              <div className="ops-progress-label">
                                <span>进度</span>
                                <strong style={{ color: item.ownerColor }}>
                                  {item.progress}%
                                </strong>
                              </div>
                            </div>
                            <div className="ops-task-footer ops-task-footer-progress">
                              <span
                                className="ops-task-chip"
                                style={{ background: item.tagBg, color: item.tagColor }}
                              >
                                {item.label}
                              </span>
                              <span
                                className={
                                  item.statusText === "紧急"
                                    ? "ops-task-meta alert"
                                    : "ops-task-meta"
                                }
                              >
                                {item.statusText || item.timeText}
                              </span>
                            </div>
                            </>
                          ) : null}
                          {typeof item.score === "number" ? (
                            <div className="ops-task-rating" aria-label={`评分 ${item.score}`}>
                              {Array.from({ length: 5 }, (_, index) => (
                                <i
                                  key={`${item.id}-star-${index}`}
                                  className={
                                    item.score >= index + 0.5
                                      ? "fas fa-star"
                                      : "far fa-star"
                                  }
                                />
                              ))}
                              <strong>{item.score}</strong>
                            </div>
                          ) : null}
                          {typeof item.progress !== "number" ? (
                            <div className="ops-task-footer">
                              <span
                                className="ops-task-chip"
                                style={{ background: item.tagBg, color: item.tagColor }}
                              >
                                {item.label}
                              </span>
                              <span
                                className={
                                  item.statusText === "紧急"
                                    ? "ops-task-meta alert"
                                    : "ops-task-meta"
                                }
                              >
                                {item.statusText || item.timeText}
                              </span>
                            </div>
                          ) : null}
                        </article>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            </div>
          ) : null}

          {currentView === "tasks" ? (
            <TaskViewPanel onOpenEmployeeChat={handleOpenTaskEmployeeChat} />
          ) : null}

          {currentView === "chat" ? (
            <div className="chat-container">
              <div className="chat-header">
                <div className="chat-header-main">
                  <div style={{ fontSize: "13px", fontWeight: 600 }}>
                    {isAlarmWorkbenchMode
                      ? `${currentEmployee.name} - 告警工单处置`
                      : `${currentEmployee.name} - 智能服务`}
                  </div>
                  {isRemoteEmployee || isAlarmWorkbenchMode ? (
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
                      <button className="history-btn" onClick={() => void handleOpenHistory()}>
                        <i className="fas fa-history" /> 历史信息
                      </button>
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
                      <button className="history-btn" onClick={() => void handleOpenHistory()}>
                        <i className="fas fa-history" /> 历史信息
                      </button>
                      {capabilityOptions.map((item) => (
                        <button
                          key={item.id}
                          className={
                            activeCapability === item.id
                              ? "capability-tag active"
                              : "capability-tag"
                          }
                          onClick={() => setActiveCapability(item.id)}
                        >
                          <i className={`fas ${item.icon}`} /> {item.label}
                        </button>
                      ))}
                    </>
                  )}
                </div>
              </div>

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

              {currentView === "chat" ? (
                <>
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
                    <div className="input-wrapper">
                      <div className={isCreatingChat ? "input-box disabled" : "input-box"}>
                        <i className="fas fa-comment-dots" />
                        <input
                          type="text"
                          value={inputMessage}
                          disabled={isCreatingChat || isStreaming}
                          onChange={(event) => setInputMessage(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" && !isStreaming) {
                              void handleSendMessage();
                            }
                          }}
                          placeholder={`向 ${currentEmployee.name} 描述您的需求...`}
                        />
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
                </>
              ) : null}
            </div>
          ) : null}
            </>
          )}
        </div>
      </div>

      {historyVisible ? (
        <div className="history-modal show" onClick={() => setHistoryVisible(false)}>
          <div className="history-content" onClick={(event) => event.stopPropagation()}>
            <div className="history-header">
              <h3>
                <i className="fas fa-history" /> 历史信息
              </h3>
              <button className="history-close" onClick={() => setHistoryVisible(false)}>
                <i className="fas fa-times" />
              </button>
            </div>
            <div className="history-body">
              {historyLoading ? (
                <div className="history-empty">
                  <i className="fas fa-spinner fa-spin" />
                  <p>正在加载历史会话...</p>
                </div>
              ) : historyError ? (
                <div className="history-empty">
                  <i className="fas fa-triangle-exclamation" />
                  <p>{historyError}</p>
                </div>
              ) : sessionList.length ? (
                <div className="history-timeline">
                  {sessionList.map((session) => (
                    <button
                      key={session.id}
                      className={
                        session.id === (isRemoteEmployee ? currentChatId : currentSessionId)
                          ? "history-item active-session"
                          : "history-item"
                      }
                      onClick={() => void handleSelectHistory(session)}
                    >
                      <div className="history-time">
                        {new Date(
                          session.updatedAt || session.createdAt || new Date().toISOString(),
                        ).toLocaleString("zh-CN")}
                      </div>
                      <div className="history-title">{session.title}</div>
                      <div className="history-detail">
                        {session.detail || `${session.messages?.length || 0} 条消息`}
                      </div>
                      <div className="history-agent-tag">
                        <i className={`fas ${currentEmployee.icon}`} />
                        {session.tag || currentEmployee.name}
                      </div>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="history-empty">
                  <i className="fas fa-clock-rotate-left" />
                  <p>当前暂无历史会话</p>
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
