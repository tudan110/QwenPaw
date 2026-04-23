export type AlarmAnalystCardPriority = "p0" | "p1" | "p2";
export type AlarmAnalystCardEvidenceKind = "alarm" | "metric" | "cmdb" | "tool";

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
  }>;
  evidence: Array<{
    kind: AlarmAnalystCardEvidenceKind;
    title: string;
    summary: string;
  }>;
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

  const cardsByMessageId = new Map(
    cards
      .filter((card) => card?.source?.messageId)
      .map((card) => [String(card.source.messageId), card] as const),
  );
  const cardsByReportMarkdown = new Map(
    cards
      .filter((card) => card?.rawReportMarkdown)
      .map((card) => [String(card.rawReportMarkdown).trim(), card] as const),
  );

  return messages.map((message) => {
    const sourceMessageId = getAlarmAnalystSourceMessageId(message);
    const reportMarkdown = getAlarmAnalystReportMarkdown(message);
    const card = (
      (sourceMessageId ? cardsByMessageId.get(sourceMessageId) : null) ||
      (reportMarkdown ? cardsByReportMarkdown.get(reportMarkdown) : null)
    );
    if (!card) {
      return message;
    }
    return {
      ...message,
      alarmAnalystCard: card,
    };
  });
}
