const TIMEOUT_ALARM_TITLE = "应用接口响应超时";
export const ALARM_WORKORDER_ENTRY = "alarm-workorders";
export const ALARM_WORKORDER_LIMIT = 5;
export const PORTAL_FAULT_WORKORDER_MARKER = "# PORTAL FAULT WORKORDER MODE";

export type VisualBlock = {
  type: "echarts" | "mermaid" | "portal-visualization";
  raw: string;
};

function looksLikeEChartsConfig(raw: string) {
  const text = String(raw || "").trim();
  if (!text.startsWith("{") || !text.endsWith("}")) {
    return false;
  }

  try {
    const parsed = JSON.parse(text) as Record<string, unknown>;
    return Boolean(
      parsed
      && typeof parsed === "object"
      && (
        Array.isArray(parsed.series)
        || Array.isArray((parsed as { xAxis?: { data?: unknown[] } }).xAxis?.data)
        || "__mockStream" in parsed
      ),
    );
  } catch {
    return false;
  }
}

export function selectAlarmWorkbenchVisibleWorkorders(workorders: any[] = []) {
  if (!Array.isArray(workorders) || !workorders.length) {
    return [];
  }

  const timeoutEntries = workorders.filter((item) =>
    String(item?.title || "").includes(TIMEOUT_ALARM_TITLE),
  );

  if (timeoutEntries.length) {
    return timeoutEntries.slice(0, 1);
  }

  return workorders.slice(0, 1);
}

export function mergeStreamingText(currentText: string, incomingText: string) {
  const current = String(currentText || "");
  const incoming = String(incomingText || "");

  if (!incoming) {
    return current;
  }
  if (!current) {
    return incoming;
  }
  if (incoming.startsWith(current)) {
    return incoming;
  }
  if (current.endsWith(incoming)) {
    return current;
  }

  const maxOverlap = Math.min(current.length, incoming.length);
  for (let size = maxOverlap; size > 0; size -= 1) {
    if (current.slice(-size) === incoming.slice(0, size)) {
      return `${current}${incoming.slice(size)}`;
    }
  }

  return `${current}${incoming}`;
}

export function buildEmployeePagePath(employee: any) {
  if (employee?.id === "fault" && employee?.urgent) {
    return `/employee/${employee.id}?entry=${ALARM_WORKORDER_ENTRY}`;
  }
  return `/employee/${employee.id}`;
}

export function getSeverityClassName(severityLevel: any) {
  if (String(severityLevel) === "1") {
    return "severity-critical";
  }
  if (String(severityLevel) === "2") {
    return "severity-major";
  }
  if (String(severityLevel) === "3") {
    return "severity-minor";
  }
  return "severity-info";
}

export function createWelcomeMessage(employee: any) {
  return createAgentMessage(employee, {
    id: `welcome-${employee.id}-${Date.now()}`,
    content: employee.welcome,
  });
}

export function createAgentMessage(employee: any, overrides: Record<string, any> = {}) {
  return {
    id: `agent-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    type: "agent",
    icon: employee.icon,
    gradient: "linear-gradient(135deg, var(--primary), var(--purple))",
    content: "",
    processBlocks: [],
    ...overrides,
  };
}

export function normalizeDisposalOperationPayload(action: any) {
  if (!action) {
    return null;
  }

  const rawStatus = String(action.status || "").trim().toLowerCase();
  let normalizedStatus = rawStatus || "ready";

  if (["completed", "complete", "done", "executed", "finished", "success"].includes(rawStatus)) {
    normalizedStatus = "success";
  } else if (["running", "in_progress", "in-progress", "pending_execution"].includes(rawStatus)) {
    normalizedStatus = "running";
  } else if (!rawStatus && (action.recoveryVerified || action.executedAt)) {
    normalizedStatus = "success";
  }

  return {
    ...action,
    status: normalizedStatus,
  };
}

export function buildAgentMessageFromPayload(
  payload: any,
  { employee, id }: { employee?: any; id?: string } = {},
) {
  if (!employee || !payload) {
    return null;
  }

  return createAgentMessage(employee, {
    id: id || `fault-disposal-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    content: payload.content || "",
    processBlocks: payload.processBlocks || [],
    disposalOperation: normalizeDisposalOperationPayload(payload.action),
    streaming: false,
  });
}

export function createAlarmWorkorderMessage(employee: any, overrides: Record<string, any> = {}) {
  return createAgentMessage(employee, {
    content: "",
    workorders: [],
    workordersLoading: false,
    workordersError: "",
    ...overrides,
  });
}

export function createUserMessage(content: string) {
  return {
    id: `user-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    type: "user",
    content,
  };
}

export function createRemoteSessionId(employeeId: string) {
  return `${getPortalSessionPrefix(employeeId)}${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function buildFaultWorkbenchVisiblePrompt(workorder: any) {
  return `去处置工单 ${workorder.workorderNo}：${workorder.title}`;
}

export function buildFaultWorkbenchChatName(workorder: any) {
  return `故障处置 · ${workorder.title} · ${workorder.workorderNo}`.slice(0, 80);
}

export function buildFaultWorkbenchChatMeta(workorder: any) {
  return {
    source: "portal-fault-workorder",
    workorderNo: workorder.workorderNo,
    title: workorder.title,
  };
}

export function buildFaultWorkbenchContextPayload(
  workorder: any,
  workorders: any[],
  extras: Record<string, any> = {},
) {
  const compactWorkorders = selectRelevantWorkordersForSkill(workorder, workorders).map(
    compactWorkorderForSkill,
  );
  return {
    entryWorkorder: compactWorkorderForSkill(workorder),
    workorders: compactWorkorders,
    tags: ["portal", "fault-disposal", "workorder-driven"],
    source: "portal-chat",
    ...extras,
  };
}

export function buildFaultWorkbenchDiagnosePrompt(workorder: any, workorders: any[]) {
  return [
    PORTAL_FAULT_WORKORDER_MARKER,
    "请按 CoPAW 标准故障处置流程继续当前工单分析，优先调用 fault-disposal skill。",
    "要求：保持在当前聊天会话中完成，不要创建子会话；先完成根因分析与处置建议，暂时不要直接执行动作；输出精炼 markdown，并保留 portal-action 代码块。",
    "执行约束：不要把脚本命令原样回复给用户；如果已识别为工单驱动故障处置，直接进入 skill 分析；不要先查询实时告警列表或重复做无关信息收集。",
    "",
    "【工单上下文(JSON)】",
    "```json",
    JSON.stringify(buildFaultWorkbenchContextPayload(workorder, workorders), null, 2),
    "```",
    "",
    "---",
    buildFaultWorkbenchVisiblePrompt(workorder),
  ].join("\n");
}

export function buildFaultWorkbenchExecutePrompt(workorder: any, workorders: any[], action: any) {
  return [
    PORTAL_FAULT_WORKORDER_MARKER,
    "请按 CoPAW 标准故障处置流程继续当前工单，并执行已经确认的建议动作，优先调用 fault-disposal skill。",
    "要求：保持在当前聊天会话中执行，不要创建子会话；完成动作后返回恢复验证结论，正文保持精炼 markdown。",
    "执行约束：不要把脚本命令原样回复给用户；不要重复查询无关告警列表；基于下方建议动作和工单上下文完成执行与验证。",
    "",
    "【建议动作(JSON)】",
    "```json",
    JSON.stringify(compactActionForSkill(action || {}), null, 2),
    "```",
    "",
    "【工单上下文(JSON)】",
    "```json",
    JSON.stringify(
      buildFaultWorkbenchContextPayload(workorder, workorders, {
        confirmedAction: action || {},
      }),
      null,
      2,
    ),
    "```",
    "",
    "---",
    `执行建议动作：${action?.title || "故障处置动作"}`,
  ].join("\n");
}

function compactWorkorderForSkill(workorder: any) {
  if (!workorder || typeof workorder !== "object") {
    return {};
  }
  return {
    id: workorder.id,
    workorderNo: workorder.workorderNo,
    title: workorder.title,
    description: workorder.description,
    deviceName: workorder.deviceName,
    manageIp: workorder.manageIp,
    locateName: workorder.locateName,
    eventTime: workorder.eventTime,
    severity: workorder.severity,
    severityLevel: workorder.severityLevel,
    status: workorder.status,
    speciality: workorder.speciality,
    region: workorder.region,
    actionCount: workorder.actionCount,
    alarmText: workorder.alarmText,
  };
}

function compactActionForSkill(action: any) {
  if (!action || typeof action !== "object") {
    return {};
  }
  return {
    id: action.id,
    type: action.type,
    title: action.title,
    summary: action.summary,
    status: action.status,
    riskLevel: action.riskLevel || action.risk_level,
    sessionId: action.sessionId,
    sqlId: action.sqlId,
    targetSummary: action.targetSummary,
    sourceWorkorderNo: action.sourceWorkorderNo,
    rootCauseWorkorderNo: action.rootCauseWorkorderNo,
    deviceName: action.deviceName,
    manageIp: action.manageIp,
    locateName: action.locateName,
  };
}

function selectRelevantWorkordersForSkill(entryWorkorder: any, workorders: any[] = []) {
  const list = Array.isArray(workorders) ? workorders : [];
  const result = [];
  const seen = new Set<string>();

  const push = (item: any) => {
    const key = String(item?.workorderNo || item?.id || "");
    if (!key || seen.has(key)) {
      return;
    }
    seen.add(key);
    result.push(item);
  };

  push(entryWorkorder);
  list
    .filter((item) => String(item?.title || "").includes("慢SQL"))
    .slice(0, 1)
    .forEach(push);

  list.slice(0, 2).forEach(push);
  return result;
}

export function buildRemoteChatName(employeeName: string, firstMessage: string) {
  const trimmed = (firstMessage || "").trim();
  if (!trimmed) {
    return `${employeeName} · ${new Date().toLocaleString("zh-CN")}`;
  }
  return trimmed.slice(0, 24);
}

export function normalizeRemoteSessions(chats: any[] = [], employeeId: string) {
  const allowedPrefixes = getRemoteSessionPrefixes(employeeId);
  const scopedChats = [...(chats || [])]
    .filter((chat) =>
      allowedPrefixes.some((prefix) =>
        String(chat.session_id || "").startsWith(prefix),
      ),
    )
    .sort((left, right) => {
      const leftTime = new Date(left.updated_at || left.created_at || 0).getTime();
      const rightTime = new Date(right.updated_at || right.created_at || 0).getTime();
      return rightTime - leftTime;
    });

  const dedupedChats = [];
  const seenKeys = new Set();

  for (const chat of scopedChats) {
    const dedupeKey = buildRemoteSessionDedupeKey(chat, employeeId);
    if (seenKeys.has(dedupeKey)) {
      continue;
    }
    seenKeys.add(dedupeKey);
    dedupedChats.push(chat);
  }

  return dedupedChats.map((chat) => ({
    id: chat.id,
    sessionId: chat.session_id,
    title: buildRemoteSessionTitle(chat, employeeId),
    updatedAt: chat.updated_at || chat.created_at || new Date().toISOString(),
    status: chat.status || "idle",
    detail: buildRemoteSessionDetail(chat),
    tag: chat.status === "running" ? "进行中" : "历史记录",
    meta: chat.meta || {},
  }));
}

export function normalizeRemoteHistoryMessages(
  historyMessages: any[] = [],
  employee: any,
  session: any,
) {
  const normalizedMessages = [];
  let activeAgentMessage = null;

  for (const message of historyMessages || []) {
    if (message.role === "user" && (!message.type || message.type === "message")) {
      const rawText = sanitizeRemoteUserText(extractCopawMessageText(message));
      if (!rawText) {
        continue;
      }
      activeAgentMessage = null;
      normalizedMessages.push({
        id: message.id || `user-${normalizedMessages.length}`,
        type: "user",
        content: rawText,
      });
      continue;
    }

    if (!activeAgentMessage) {
      activeAgentMessage = createAgentMessage(employee, {
        id: message.id || `agent-${normalizedMessages.length}`,
        content: "",
        processBlocks: [],
      });
      normalizedMessages.push(activeAgentMessage);
    }

    if (message.role === "assistant" && message.type === "reasoning") {
      const block = buildThinkingBlock(message);
      if (block.content) {
        activeAgentMessage.processBlocks = mergeProcessBlocks(
          activeAgentMessage.processBlocks,
          [block],
        );
      }
      continue;
    }

    if (message.type === "plugin_call" || message.type === "plugin_call_output") {
      const block = buildToolBlock(message);
      if (block.content) {
        activeAgentMessage.processBlocks = mergeProcessBlocks(
          activeAgentMessage.processBlocks,
          [block],
        );
      }
      continue;
    }

    if (message.role === "assistant" && (!message.type || message.type === "message")) {
      const text = extractCopawMessageText(message);
      if (!text) {
        continue;
      }
      activeAgentMessage.content = activeAgentMessage.content
        ? `${activeAgentMessage.content}\n\n${text}`
        : text;
    }
  }

  return normalizedMessages.filter((message) => {
    if (message.type === "user") {
      return Boolean(message.content);
    }
    return Boolean(message.content || message.processBlocks?.length);
  });
}

export function extractCopawMessageText(message: any) {
  return normalizeContentToText(message?.content).trim();
}

export function buildThinkingBlock(message: any) {
  return {
    id: message.id || `thinking-${Date.now()}`,
    kind: "thinking",
    title: "Thinking",
    subtitle: "思考过程",
    icon: "fa-brain",
    content: extractCopawMessageText(message),
  };
}

export function buildToolBlock(message: any) {
  const payload = extractMessageDataPayload(message);
  const toolName = payload?.name || "tool";
  const toolCallId = payload?.call_id || payload?.tool_call_id || payload?.id || "";
  const inputContent =
    message.type === "plugin_call" ? normalizeToolPayload(payload?.arguments) : "";
  const outputContent =
    message.type === "plugin_call_output" ? normalizeToolPayload(payload?.output) : "";

  return {
    id: message.id || `${message.type}-${Date.now()}`,
    kind: "tool",
    title: toolName,
    subtitle: "工具调用",
    icon: "fa-screwdriver-wrench",
    toolName,
    toolCallId,
    inputContent,
    outputContent,
    content: inputContent || outputContent || toolName,
  };
}

function extractMessageDataPayload(message: any) {
  const content = Array.isArray(message?.content) ? message.content : [];
  const dataItem = content.find((item: any) => item?.type === "data");
  return dataItem?.data || null;
}

export function mergeProcessBlocks(existingBlocks: any[] = [], incomingBlocks: any[] = []) {
  return incomingBlocks.reduce((mergedBlocks, incomingBlock) => {
    if (!incomingBlock) {
      return mergedBlocks;
    }

    if (incomingBlock.kind !== "tool") {
      return mergedBlocks.some((item) => item.id === incomingBlock.id)
        ? mergedBlocks
        : [...mergedBlocks, incomingBlock];
    }

    const targetIndex = findMatchingToolBlockIndex(mergedBlocks, incomingBlock);
    if (targetIndex === -1) {
      return mergedBlocks.some((item) => item.id === incomingBlock.id)
        ? mergedBlocks
        : [...mergedBlocks, incomingBlock];
    }

    const nextBlocks = [...mergedBlocks];
    nextBlocks[targetIndex] = mergeToolTraceBlock(nextBlocks[targetIndex], incomingBlock);
    return nextBlocks;
  }, [...existingBlocks]);
}

function findMatchingToolBlockIndex(blocks: any[], incomingBlock: any) {
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const candidate = blocks[index];
    if (candidate?.kind !== "tool") {
      continue;
    }

    const candidateKey = candidate.toolCallId || candidate.toolName || candidate.title;
    const incomingKey =
      incomingBlock.toolCallId || incomingBlock.toolName || incomingBlock.title;
    if (!candidateKey || !incomingKey || candidateKey !== incomingKey) {
      continue;
    }

    if (incomingBlock.inputContent && candidate.inputContent) {
      continue;
    }
    if (incomingBlock.outputContent && candidate.outputContent) {
      continue;
    }

    return index;
  }

  return -1;
}

function mergeToolTraceBlock(existingBlock: any, incomingBlock: any) {
  const inputContent = existingBlock.inputContent || incomingBlock.inputContent || "";
  const outputContent = existingBlock.outputContent || incomingBlock.outputContent || "";

  return {
    ...existingBlock,
    title: existingBlock.title || incomingBlock.title,
    subtitle: "工具调用",
    icon: "fa-screwdriver-wrench",
    toolName: existingBlock.toolName || incomingBlock.toolName,
    toolCallId: existingBlock.toolCallId || incomingBlock.toolCallId,
    inputContent,
    outputContent,
    content: inputContent || outputContent || existingBlock.content || incomingBlock.content,
  };
}

function normalizeToolPayload(rawValue: any) {
  if (!rawValue) {
    return "";
  }

  if (typeof rawValue !== "string") {
    return `\`\`\`json\n${JSON.stringify(rawValue, null, 2)}\n\`\`\``;
  }

  const trimmed = rawValue.trim();
  if (!trimmed) {
    return "";
  }

  const parsed = parseJsonSafely(trimmed);
  if (!parsed) {
    return `\`\`\`\n${trimmed}\n\`\`\``;
  }

  if (Array.isArray(parsed)) {
    const textContent = parsed
      .map((item: any) => (item?.type === "text" && item?.text ? item.text : ""))
      .filter(Boolean)
      .join("\n\n")
      .trim();
    if (textContent) {
      return textContent;
    }
  }

  return `\`\`\`json\n${JSON.stringify(parsed, null, 2)}\n\`\`\``;
}

function parseJsonSafely(rawValue: string) {
  try {
    return JSON.parse(rawValue);
  } catch {
    return null;
  }
}

function normalizeContentToText(content: any): string {
  if (!content) {
    return "";
  }
  if (typeof content === "string") {
    return content;
  }
  if (Array.isArray(content)) {
    return content.map((item) => normalizeContentToText(item)).join("");
  }
  if (typeof content === "object") {
    if (typeof content.text === "string") {
      return content.text;
    }
    if (Array.isArray(content.content)) {
      return normalizeContentToText(content.content);
    }
  }
  return "";
}

function sanitizeRemoteUserText(content: string) {
  const normalized = String(content || "");
  if (
    normalized.includes(PORTAL_FAULT_WORKORDER_MARKER) &&
    normalized.includes("\n---\n")
  ) {
    const segments = normalized.split(/\n---\n/);
    const candidate = segments[segments.length - 1]?.trim();
    return candidate || normalized;
  }

  if (!normalized.includes("# BOOTSTRAP MODE") || !normalized.includes("\n---")) {
    return normalized;
  }

  const segments = normalized.split(/\n---\n/);
  const candidate = segments[segments.length - 1]?.trim();
  return candidate || normalized;
}

export function extractPortalActionPayload(content: string) {
  const rawContent = unwrapOuterMarkdownFence(String(content || ""));
  const match = rawContent.match(/```portal-action\s*([\s\S]*?)```/i);
  if (!match?.[1]) {
    return null;
  }

  try {
    return normalizeDisposalOperationPayload(JSON.parse(match[1].trim()));
  } catch {
    return null;
  }
}

export function buildSessionTitle(employeeName: string, nextMessages: any[]) {
  const firstUserMessage = nextMessages.find((item) => item.type === "user");
  if (!firstUserMessage) {
    return `${employeeName} · ${new Date().toLocaleString("zh-CN")}`;
  }
  return `${employeeName} · ${firstUserMessage.content.slice(0, 24)}`;
}

export function formatChatStatus(status: string) {
  if (status === "running") {
    return "进行中";
  }
  if (status === "idle") {
    return "已完成";
  }
  return status || "未知";
}

export function getPortalSessionPrefix(employeeId: string) {
  return `portal-${employeeId}-`;
}

function getRemoteSessionPrefixes(employeeId: string) {
  return [getPortalSessionPrefix(employeeId)];
}

function buildRemoteSessionDedupeKey(chat: any, employeeId: string) {
  return String(chat?.session_id || chat?.id || Math.random());
}

function isFaultWorkbenchChat(chat: any) {
  return String(chat?.meta?.source || "") === "portal-fault-workorder";
}

function buildRemoteSessionTitle(chat: any, employeeId: string) {
  if (employeeId === "fault" && isFaultWorkbenchChat(chat)) {
    const workorderNo = String(chat?.meta?.workorderNo || "").trim();
    const title = String(chat?.meta?.title || "").trim();
    if (workorderNo && title) {
      return `故障处置 · ${title} · ${workorderNo}`;
    }
    if (workorderNo) {
      return `故障处置 · ${workorderNo}`;
    }
  }
  return chat?.name || "未命名会话";
}

function buildRemoteSessionDetail(chat: any) {
  const statusLabel = formatChatStatus(chat?.status);
  const workorderNo = String(chat?.meta?.workorderNo || "").trim();
  if (workorderNo) {
    return `工单：${workorderNo} · 状态：${statusLabel}`;
  }
  return `状态：${statusLabel}`;
}

export function normalizeMarkdownDisplayContent(
  content: string,
  { isStreaming = false }: { isStreaming?: boolean } = {},
) {
  let normalized = unwrapOuterMarkdownFence(String(content || ""))
    .replace(/```portal-action\s*[\s\S]*?```/gi, "")
    .replace(/<br\s*\/?>\s*<br\s*\/?>/gi, "\n\n")
    .replace(/<br\s*\/?>/gi, "  \n")
    .replace(/\n{3,}/g, "\n\n");

  if (isStreaming) {
    normalized = normalized
      .replace(/```echarts\s*[\s\S]*?```/gi, "")
      .replace(/```mermaid\s*[\s\S]*?```/gi, "")
      .replace(/```portal-visualization\s*[\s\S]*?```/gi, "")
      .replace(/```portal-action[\s\S]*$/i, "")
      .replace(/```json\s*([\s\S]*?)```/gi, (fullMatch, raw) =>
        looksLikeEChartsConfig(raw) ? "" : fullMatch,
      )
      .replace(/```echarts[\s\S]*$/i, "\n\n> 图表加载中，正在生成可视化配置...\n\n")
      .replace(/```mermaid[\s\S]*$/i, "\n\n> 拓扑图加载中，正在生成可视化配置...\n\n")
      .replace(/```portal-visualization[\s\S]*$/i, "\n\n> 图表加载中，正在生成可视化配置...\n\n")
      .replace(/```json[\s\S]*$/i, "\n\n> 图表加载中，正在生成可视化配置...\n\n")
      .replace(/`{1,3}/g, "");
  } else {
    normalized = normalized.replace(/```(?:echarts|mermaid|portal-visualization)\s*[\s\S]*?```/gi, "");
    normalized = normalized.replace(/```json\s*([\s\S]*?)```/gi, (fullMatch, raw) => {
      return looksLikeEChartsConfig(raw) ? "" : fullMatch;
    });
  }

  return normalized;
}

export function extractVisualBlocks(content: string): VisualBlock[] {
  const normalized = unwrapOuterMarkdownFence(String(content || ""));
  const matches = normalized.matchAll(/```([\w-]+)?\s*([\s\S]*?)```/gi);
  const blocks: VisualBlock[] = [];

  for (const match of matches) {
    const type = String(match[1] || "").toLowerCase();
    const raw = String(match[2] || "").trim();
    if (!raw) {
      continue;
    }
    if (type === "echarts" || (type === "json" && looksLikeEChartsConfig(raw))) {
      blocks.push({
        type: "echarts",
        raw,
      });
      continue;
    }
    if (type === "mermaid") {
      blocks.push({
        type: "mermaid",
        raw,
      });
      continue;
    }
    if (type === "portal-visualization") {
      blocks.push({
        type: "portal-visualization",
        raw,
      });
    }
  }

  return blocks;
}

function unwrapOuterMarkdownFence(content: string) {
  const normalized = String(content || "").trim();
  const match = normalized.match(/^```(?:markdown|md|text)?\s*\n([\s\S]*?)\n```$/i);
  if (!match?.[1]) {
    return normalized;
  }
  return match[1].trim();
}
