import {
  Component,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
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
import { deleteChat, updateChat } from "../api/copawChat";
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
  buildPortalHomePath,
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
};

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
    "@数据洞察员 当前有哪些设备？",
    "@故障速应 数据库响应很慢，请帮我定位",
    "@知库小典 Oracle 死锁怎么处理？",
    "帮我判断这个问题应该交给哪个数字员工",
  ],
  welcome: "",
} as const;

const operationsBoardDots = {
  pending: "pending",
  running: "running",
  completed: "completed",
  closed: "closed",
} as const;

type PendingPortalDispatch = {
  token: string;
  targetEmployeeId: string;
  content: string;
  visibleContent: string;
};

type PortalLocationState = {
  pendingPortalDispatch?: PendingPortalDispatch;
};

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
    { employee: "数据洞察员", keywords: ["设备", "指标", "报表", "趋势", "性能", "查询", "可用性"] },
    { employee: "故障速应", keywords: ["故障", "异常", "超时", "中断", "恢复", "慢", "报警", "告警"] },
    { employee: "资产管家", keywords: ["资产", "纳管", "扫描", "发现", "拓扑", "资源"] },
    { employee: "巡弋小卫", keywords: ["巡检", "健康", "检查", "日报", "周报"] },
    { employee: "知库小典", keywords: ["怎么", "最佳实践", "方案", "知识", "原理"] },
    { employee: "工单管家", keywords: ["工单", "审批", "转派", "流程"] },
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
    "- `@数据洞察员 当前有哪些设备？`",
    "- `@故障速应 数据库响应很慢，请帮我定位`",
    "- `@知库小典 Oracle 死锁怎么处理？`",
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
  const selectedEmployee = useMemo(() => {
    if (!employeeId) {
      return null;
    }
    return digitalEmployees.find((item) => item.id === employeeId) || null;
  }, [employeeId]);
  const portalHomeEmployee = useMemo(() => ({ ...PORTAL_HOME_EMPLOYEE }), []);
  const currentEmployee = selectedEmployee || portalHomeEmployee;
  const routeSection = forcedSection || null;
  const remoteAgentId = selectedEmployee
    ? (REMOTE_AGENT_IDS[selectedEmployee.id] || null)
    : PORTAL_HOME_AGENT_ID;
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
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const handledPendingDispatchRef = useRef("");
  const chatInputRef = useRef<HTMLInputElement | null>(null);
  const homeComposerRef = useRef<HTMLTextAreaElement | null>(null);
  const employeeDropdownRef = useRef<HTMLDivElement | null>(null);
  const [historyEditingId, setHistoryEditingId] = useState("");
  const [historyDraftTitle, setHistoryDraftTitle] = useState("");
  const [historyActionSessionId, setHistoryActionSessionId] = useState("");
  const [historyActionError, setHistoryActionError] = useState("");

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
  const [lastSidebarEmployeeId, setLastSidebarEmployeeId] = useState<string | null>(null);
  const currentSidebarEmployee = useMemo(() => {
    const employeeId = selectedEmployee?.id || lastSidebarEmployeeId || sidebarEmployees[0]?.id || null;
    return sidebarEmployees.find((employee) => employee.id === employeeId) || sidebarEmployees[0] || null;
  }, [lastSidebarEmployeeId, selectedEmployee?.id, sidebarEmployees]);
  const otherSidebarEmployees = useMemo(
    () => sidebarEmployees.filter((employee) => employee.id !== currentSidebarEmployee?.id),
    [currentSidebarEmployee?.id, sidebarEmployees],
  );

  const safeMessages = ensureObjectArray(messages);
  const safeExecutionList = ensureObjectArray<ExecutionRecord>(executionList);
  const safeCapabilities = ensureStringArray(currentEmployee?.capabilities);
  const safeQuickCommands = ensureStringArray(currentEmployee?.quickCommands);
  const showModelSelector = currentView === "chat";
  const isModelConfigMode = activeAdvancedPanel === "model-config";
  const isTokenUsageMode = activeAdvancedPanel === "token-usage";
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
              <i className="fas fa-brain" />
            </div>
            <div className="logo-text">
              <h1>{portalAppTitle}</h1>
              <span>智能 · 高效 · 自动化</span>
            </div>
          </button>

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
          {!isPortalHomeChat ? (
            <button
              type="button"
              className="ops-board-theme-toggle portal-global-theme-toggle"
              onClick={() => setPageTheme((value) => (value === "light" ? "dark" : "light"))}
              aria-label="切换整页主题"
              title="切换整页主题"
            >
              <i className={`fas ${pageTheme === "light" ? "fa-moon" : "fa-sun"}`} />
            </button>
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
          ) : (
            <>
          {!isPortalHomeChat ? (
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
          ) : null}

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
            <div className={isPortalHomeChat ? "chat-container portal-home-chat" : "chat-container"}>
              {showPortalHomeHero ? (
                <div className="portal-home-stage">
                  <div className="portal-home-toolbar">
                    <button
                      type="button"
                      className="ops-board-theme-toggle portal-home-theme-toggle"
                      onClick={() => setPageTheme((value) => (value === "light" ? "dark" : "light"))}
                      aria-label="切换整页主题"
                      title="切换整页主题"
                    >
                      <i className={`fas ${pageTheme === "light" ? "fa-moon" : "fa-sun"}`} />
                    </button>
                  </div>
                  <div className="portal-home-hero">
                    <div className="portal-home-orbit">
                      <span className="portal-home-orbit-ring outer" />
                      <span className="portal-home-orbit-ring inner" />
                      <span className="portal-home-orbit-core">
                        <i className="fas fa-brain" />
                      </span>
                    </div>
                    <h2>数字员工聊天门户</h2>
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
                      placeholder="输入 @ 选择数字员工，或直接输入您的问题..."
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
                            <i className="fas fa-history" /> 历史会话
                          </button>
                          <button className="history-btn new-chat-btn" onClick={handleStartNewConversation}>
                            <i className="fas fa-plus" /> 新对话
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
                            <i className="fas fa-history" /> 历史会话
                          </button>
                          <button className="history-btn new-chat-btn" onClick={handleStartNewConversation}>
                            <i className="fas fa-plus" /> 新对话
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                  ) : null}

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
                        输入自然语言即可开始对话，使用 <code>@数字员工名</code> 可直接切换到指定员工。
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
              )}
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
                <i className="fas fa-history" /> 历史会话
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
                  <p>正在加载历史会话...</p>
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
