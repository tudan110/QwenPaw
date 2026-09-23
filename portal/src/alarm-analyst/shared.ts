import {
  PORTAL_ALARM_ANALYST_CARD_MARKER,
  unwrapPortalAlarmAnalystCardContent,
} from "../pages/digital-employee/helpers.ts";

export type AlarmAnalystCardPriority = "p0" | "p1" | "p2";
export type AlarmAnalystCardEvidenceKind = "alarm" | "metric" | "cmdb" | "tool";

// One row of the report's "候选根因" Top-N table.
// `confidence` keeps the raw report text (e.g. "86%").
export type AlarmAnalystCardRootCauseCandidate = {
  rank: number;
  reason: string;
  resourceName?: string;
  confidence: string;
  evidence?: string;
};

export type AlarmAnalystWorkorderProposal = {
  proposalId: string;
  idempotencyKey: string;
  enabled: boolean;
  title: string;
  summary: string;
  alarmId: string;
  resourceId?: string;
  deviceName?: string;
  manageIp?: string;
  eventTime?: string;
  severity?: string;
  rootCauseSummary?: string;
  suggestions: string[];
  expiresInSeconds: number;
};

export type AlarmAnalystWorkorderStatus = {
  state: "idle" | "creating" | "created" | "failed" | "expired" | "dismissed";
  workorderId?: string;
  processId?: string;
  createdAt?: string;
  errorMessage?: string;
  lastUpdatedAt?: string;
};

export type AlarmAnalystCardV1 = {
  type: "alarm-analyst-card";
  version: "v1";
  source: {
    chatId: string;
    messageId: string;
    skillName: "alarm-analyst";
    contentHash: string;
  };
  summary: {
    title: string;
    conclusion: string;
    severity?: string;
    confidence?: "high" | "medium" | "low";
    status?: "identified" | "suspected" | "unknown";
  };
  rootCause: {
    resourceId?: string;
    resourceName?: string;
    ciId?: string;
    reason: string;
    candidates?: AlarmAnalystCardRootCauseCandidate[];
  };
  impact: {
    affectedApplications: Array<{ id?: string; name: string; type?: string }>;
    affectedResources: Array<{ id?: string; name: string; type?: string }>;
    blastRadiusText?: string;
  };
  topology: {
    nodes: Array<Record<string, unknown>>;
    edges: Array<Record<string, unknown>>;
    highlightedNodeIds?: string[];
  };
  recommendations: Array<{
    title: string;
    priority: AlarmAnalystCardPriority;
    description: string;
    risk?: string;
    actionType?: "manual" | "script" | "observe";
    // "emergency" = 紧急预案（止血）, "repair" = 根因处置（修复）,
    // "prevention" = 预防措施（中长期）
    stage?: "emergency" | "repair" | "prevention" | null;
  }>;
  evidence: Array<{
    kind: AlarmAnalystCardEvidenceKind;
    title: string;
    summary: string;
  }>;
  workorderProposal?: AlarmAnalystWorkorderProposal | null;
  workorderStatus?: AlarmAnalystWorkorderStatus | null;
  rawReportMarkdown: string;
};

export type AlarmAnalystCardRequest = {
  sessionId: string;
  chatId: string;
  messageId: string;
  employeeId: string;
  reportMarkdown: string;
  processBlocks: Array<Record<string, unknown>>;
};

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function getAlarmAnalystSessionMeta(value: any) {
  if (isPlainRecord(value?.meta)) {
    return value.meta;
  }
  if (isPlainRecord(value)) {
    return value;
  }
  return null;
}

function looksLikeAlarmAnalystHistorySession(value: unknown) {
  const text = String(value || "").trim();
  if (!text) {
    return false;
  }

  return (
    text.includes(PORTAL_ALARM_ANALYST_CARD_MARKER) ||
    /^告警分析\s*[·\-]/u.test(text) ||
    /资源\s*ID（CI\s*ID）[:：]/u.test(text) ||
    /告警时间[:：]/u.test(text) ||
    ((/告警|异常|故障/u.test(text) || /数据库锁/u.test(text)) && /CI\s*ID|资源\s*ID/u.test(text))
  );
}

function normalizeAlarmAnalystReportKey(value: unknown) {
  const text = String(value || "").trim();
  return unwrapPortalAlarmAnalystCardContent(text).trim() || text;
}

export function shouldEnableAlarmAnalystCards({
  employeeId,
  session,
}: {
  employeeId: string;
  session?: any;
}) {
  if (String(employeeId || "").trim() !== "fault") {
    return false;
  }

  const meta = getAlarmAnalystSessionMeta(session);
  if (String(meta?.source || "").trim() === "portal-fault-workorder") {
    return true;
  }
  if (String(meta?.workorderNo || "").trim()) {
    return true;
  }
  if (/^portal-fault-alarm-/u.test(String(session?.sessionId || session?.session_id || "").trim())) {
    return true;
  }

  const title = String(session?.title || session?.name || meta?.title || "").trim();
  if (/^故障处置\s*[·\-]/.test(title)) {
    return true;
  }
  if (looksLikeAlarmAnalystHistorySession(title)) {
    return true;
  }

  const detail = String(session?.detail || "").trim();
  if (/工单[:：]/.test(detail)) {
    return true;
  }
  if (looksLikeAlarmAnalystHistorySession(detail)) {
    return true;
  }

  return false;
}

export function getAlarmAnalystSourceMessageId(message: any) {
  return String(
    message?.enhancementSourceMessageId ||
      message?.backendMessageId ||
      "",
  ).trim();
}

export function getAlarmAnalystReportMarkdown(message: any) {
  const cardReport = String(message?.alarmAnalystCard?.rawReportMarkdown || "").trim();
  if (cardReport) {
    return cardReport;
  }

  const responseBlocks = Array.isArray(message?.processBlocks)
    ? message.processBlocks.filter((block: any) => block?.kind === "response" && block?.content)
    : [];
  const responseText = responseBlocks
    .map((block: any) => String(block.content || "").trim())
    .filter(Boolean)
    .join("\n\n")
    .trim();
  if (responseText) {
    return responseText;
  }
  return String(message?.content || "").trim();
}

export function shouldAttemptAlarmAnalystCardByContent(value: unknown) {
  const normalizedText = String(value || "").trim();
  if (!normalizedText) {
    return false;
  }

  return (
    normalizedText.includes(PORTAL_ALARM_ANALYST_CARD_MARKER)
    || (
      normalizedText.includes("告警分析报告")
      && normalizedText.includes("影响范围")
      && normalizedText.includes("处置建议")
    )
  );
}

export function looksLikeAlarmAnalystReportForAlarmSession(value: unknown) {
  const normalizedText = String(value || "").trim();
  if (normalizedText.length < 80) {
    return false;
  }

  const markerCount = [
    "告警分析报告",
    "告警分析 —",
    "告警分析：",
    "完整故障分析报告",
    "告警基础信息",
    "告警基本信息",
    "根因判断",
    "根因分析结论",
    "根因结论",
    "根因分析",
    "### 🔍 结论",
    "影响范围",
    "影响评估",
    "关联资源与告警",
    "处置建议",
    "处置建议（紧急程度升级）",
    "异常指标",
    "恢复验证",
    "📊 总结",
    "📌 总结",
    "## 总结",
  ].filter((marker) => normalizedText.includes(marker)).length;

  return markerCount >= 3;
}

export function buildAlarmAnalystCardRequest({
  chatId,
  sessionId,
  employeeId,
  message,
}: {
  chatId: string;
  sessionId: string;
  employeeId: string;
  message: any;
}): AlarmAnalystCardRequest | null {
  const messageId = getAlarmAnalystSourceMessageId(message);
  const reportMarkdown = getAlarmAnalystReportMarkdown(message);
  if (!chatId || !sessionId || !messageId || !reportMarkdown) {
    return null;
  }

  return {
    sessionId,
    chatId,
    messageId,
    employeeId,
    reportMarkdown,
    processBlocks: serializeAlarmAnalystProcessBlocks(message?.processBlocks),
  };
}

export function serializeAlarmAnalystProcessBlocks(processBlocks: any[] = []) {
  return processBlocks
    .filter((block) => isPlainRecord(block))
    .map((block) => ({
      kind: String(block.kind || ""),
      toolName: String(block.toolName || ""),
      toolCallId: String(block.toolCallId || ""),
      inputContent: String(block.inputContent || ""),
      outputContent: String(block.outputContent || ""),
      content: String(block.content || ""),
    }));
}

export function mergeAlarmAnalystCards(messages: any[] = [], cards: AlarmAnalystCardV1[] = []) {
  if (!Array.isArray(messages) || !messages.length || !Array.isArray(cards) || !cards.length) {
    return messages;
  }

  // A retry can persist the same logical card more than once. Keep the last
  // payload for a source message so an older replay cannot win by accident.
  const dedupedCards = [...cards].reduce<AlarmAnalystCardV1[]>((result, card) => {
    const sourceMessageId = String(card?.source?.messageId || "").trim();
    if (!sourceMessageId) {
      result.push(card);
      return result;
    }
    const previousIndex = result.findIndex(
      (candidate) => String(candidate?.source?.messageId || "").trim() === sourceMessageId,
    );
    if (previousIndex >= 0) {
      result[previousIndex] = card;
    } else {
      result.push(card);
    }
    return result;
  }, []);

  const cardsByMessageId = new Map(
    dedupedCards
      .filter((card) => card?.source?.messageId)
      .map((card) => [String(card.source.messageId), card] as const),
  );
  const cardsByReportMarkdown = new Map(
    dedupedCards
      .filter((card) => card?.rawReportMarkdown)
      .map((card) => [normalizeAlarmAnalystReportKey(card.rawReportMarkdown), card] as const),
  );

  const matchedCardKeys = new Set<AlarmAnalystCardV1>();
  const mergedMessages = messages.map((message) => {
    const sourceMessageId = getAlarmAnalystSourceMessageId(message);
    const reportMarkdown = getAlarmAnalystReportMarkdown(message);
    const card = (
      (sourceMessageId ? cardsByMessageId.get(sourceMessageId) : null) ||
      (reportMarkdown ? cardsByReportMarkdown.get(normalizeAlarmAnalystReportKey(reportMarkdown)) : null)
    );
    if (!card) {
      return message;
    }
    matchedCardKeys.add(card);
    return {
      ...message,
      alarmAnalystCard: card,
    };
  });

  // History reconstruction can assign a new assistant message id and can
  // normalize the report text differently from the streaming response. In
  // that case bind remaining cards to the remaining final report messages
  // within this already-selected alarm session. This is intentionally
  // conservative: only a one-to-one set of candidates is eligible.
  const remainingCards = dedupedCards.filter((card) => !matchedCardKeys.has(card));
  const remainingMessageIndexes = mergedMessages
    .map((message, index) => ({ message, index }))
    .filter(({ message }) => (
      message?.type === "agent"
      && !message?.alarmAnalystCard
      && looksLikeAlarmAnalystReportForAlarmSession(getAlarmAnalystReportMarkdown(message))
    ));
  if (remainingCards.length === remainingMessageIndexes.length && remainingCards.length > 0) {
    for (let index = 0; index < remainingCards.length; index += 1) {
      const target = remainingMessageIndexes[index];
      mergedMessages[target.index] = {
        ...target.message,
        alarmAnalystCard: remainingCards[index],
      };
    }
  }

  return mergedMessages;
}
