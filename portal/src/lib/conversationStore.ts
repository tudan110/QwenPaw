const STORAGE_KEY = "digital-workforce-conversations-v2";
const LEGACY_STORAGE_KEYS = [
  "digital-workforce-conversations",
];
const MAX_SESSIONS_PER_EMPLOYEE = 8;
const MAX_MESSAGES_PER_SESSION = 20;
const MAX_MESSAGE_CONTENT_LENGTH = 1200;
const FALLBACK_MESSAGE_CONTENT_LENGTH = 320;
const FALLBACK_MESSAGES_PER_SESSION = 8;
const FALLBACK_SESSIONS_PER_EMPLOYEE = 3;

export type ConversationStore = Record<string, unknown>;

type PlainRecord = Record<string, unknown>;

function isPlainRecord(value: unknown): value is PlainRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function truncateText(value: unknown, maxLength: number) {
  const text = String(value || "");
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength)}...`;
}

function cloneJsonSafe<T>(value: T): T | undefined {
  if (value === undefined) {
    return undefined;
  }

  try {
    return JSON.parse(JSON.stringify(value)) as T;
  } catch {
    return undefined;
  }
}

function sanitizeResourceImportRecord(record: unknown): PlainRecord | null {
  if (!isPlainRecord(record)) {
    return null;
  }
  return {
    previewKey: typeof record.previewKey === "string" ? record.previewKey : undefined,
    ciType: typeof record.ciType === "string" ? record.ciType : undefined,
    name: typeof record.name === "string" ? truncateText(record.name, 160) : undefined,
    category: typeof record.category === "string" ? record.category : undefined,
    generated: Boolean(record.generated),
    selected: Boolean(record.selected),
    importAction: typeof record.importAction === "string" ? record.importAction : undefined,
    existingCi: isPlainRecord(record.existingCi) ? cloneJsonSafe(record.existingCi) : undefined,
    issues: Array.isArray(record.issues) ? cloneJsonSafe(record.issues.slice(0, 12)) : undefined,
    attentionFields: Array.isArray(record.attentionFields) ? cloneJsonSafe(record.attentionFields.slice(0, 12)) : undefined,
    attributes: isPlainRecord(record.attributes) ? cloneJsonSafe(record.attributes) : undefined,
    analysisAttributes: isPlainRecord(record.analysisAttributes) ? cloneJsonSafe(record.analysisAttributes) : undefined,
    sourceRows: Array.isArray(record.sourceRows) ? cloneJsonSafe(record.sourceRows.slice(0, 4)) : undefined,
    autoFilledHints: Array.isArray(record.autoFilledHints) ? cloneJsonSafe(record.autoFilledHints.slice(0, 8)) : undefined,
  };
}

function sanitizeResourceImportGroup(group: unknown): PlainRecord | null {
  if (!isPlainRecord(group)) {
    return null;
  }
  const records = Array.isArray(group.records)
    ? group.records
      .slice(0, 120)
      .map(sanitizeResourceImportRecord)
      .filter((item): item is PlainRecord => Boolean(item))
    : [];
  return {
    ciType: typeof group.ciType === "string" ? group.ciType : undefined,
    label: typeof group.label === "string" ? truncateText(group.label, 80) : undefined,
    count: typeof group.count === "number" ? group.count : records.length,
    records,
  };
}

function sanitizeResourceImportRelation(relation: unknown): PlainRecord | null {
  if (!isPlainRecord(relation)) {
    return null;
  }
  return {
    sourceKey: typeof relation.sourceKey === "string" ? relation.sourceKey : undefined,
    targetKey: typeof relation.targetKey === "string" ? relation.targetKey : undefined,
    relationType: typeof relation.relationType === "string" ? relation.relationType : undefined,
    confidence: typeof relation.confidence === "string" ? relation.confidence : undefined,
    reason: typeof relation.reason === "string" ? truncateText(relation.reason, 220) : undefined,
    selected: Boolean(relation.selected),
    requiresModelRelation: Boolean(relation.requiresModelRelation),
    sourceType: typeof relation.sourceType === "string" ? relation.sourceType : undefined,
    targetType: typeof relation.targetType === "string" ? relation.targetType : undefined,
    sourceName: typeof relation.sourceName === "string" ? truncateText(relation.sourceName, 120) : undefined,
    targetName: typeof relation.targetName === "string" ? truncateText(relation.targetName, 120) : undefined,
  };
}

function sanitizeCiTypeMetadataMap(value: unknown): PlainRecord | undefined {
  if (!isPlainRecord(value)) {
    return undefined;
  }
  return Object.fromEntries(
    Object.entries(value).slice(0, 24).map(([key, item]) => {
      if (!isPlainRecord(item)) {
        return [key, undefined];
      }
      return [key, {
        id: item.id,
        name: typeof item.name === "string" ? item.name : key,
        alias: typeof item.alias === "string" ? item.alias : undefined,
        unique_key: typeof item.unique_key === "string" ? item.unique_key : undefined,
        system_generated_unique_key: Boolean(item.system_generated_unique_key),
        attributes: Array.isArray(item.attributes) ? cloneJsonSafe(item.attributes.slice(0, 40)) : undefined,
        attributeDefinitions: Array.isArray(item.attributeDefinitions)
          ? cloneJsonSafe(item.attributeDefinitions.slice(0, 60))
          : undefined,
        parentTypes: Array.isArray(item.parentTypes)
          ? cloneJsonSafe(item.parentTypes.slice(0, 20))
          : undefined,
      }];
    }),
  );
}

function sanitizeResourceImportFlow(flow: unknown): PlainRecord | undefined {
  if (!isPlainRecord(flow)) {
    return undefined;
  }
  const preview = isPlainRecord(flow.preview) ? flow.preview : null;
  const result = isPlainRecord(flow.result) ? flow.result : null;
  const resourceGroups = Array.isArray(flow.resourceGroups)
    ? flow.resourceGroups
      .slice(0, 20)
      .map(sanitizeResourceImportGroup)
      .filter((item): item is PlainRecord => Boolean(item))
    : undefined;
  const relations = Array.isArray(flow.relations)
    ? flow.relations
      .slice(0, 240)
      .map(sanitizeResourceImportRelation)
      .filter((item): item is PlainRecord => Boolean(item))
    : undefined;
  return {
    flowId: typeof flow.flowId === "string" ? flow.flowId : undefined,
    stage: typeof flow.stage === "string" ? flow.stage : undefined,
    status: typeof flow.status === "string" ? flow.status : undefined,
    error: typeof flow.error === "string" ? truncateText(flow.error, 240) : undefined,
    locked: Boolean(flow.locked),
    readonly: Boolean(flow.readonly),
    files: Array.isArray(flow.files) ? cloneJsonSafe(flow.files.slice(0, 6)) : undefined,
    preview: preview
      ? {
          summary: isPlainRecord(preview.summary) ? cloneJsonSafe(preview.summary) : undefined,
          analysisStatus: typeof preview.analysisStatus === "string" ? preview.analysisStatus : undefined,
          analysisIssues: Array.isArray(preview.analysisIssues)
            ? cloneJsonSafe(preview.analysisIssues.slice(0, 16))
            : undefined,
          warnings: Array.isArray(preview.warnings)
            ? preview.warnings.slice(0, 24).map((item) => truncateText(item, 220))
            : undefined,
          logs: Array.isArray(preview.logs)
            ? preview.logs.slice(0, 80).map((item) => truncateText(item, 220))
            : undefined,
          cleaningSummary: Array.isArray(preview.cleaningSummary)
            ? cloneJsonSafe(preview.cleaningSummary.slice(0, 40))
            : undefined,
          mappingSummary: Array.isArray(preview.mappingSummary)
            ? cloneJsonSafe(preview.mappingSummary.slice(0, 80))
            : undefined,
          ciTypeMetadata: sanitizeCiTypeMetadataMap(preview.ciTypeMetadata),
          structureAnalysis: isPlainRecord(preview.structureAnalysis)
            ? cloneJsonSafe(preview.structureAnalysis)
            : undefined,
          resourceGroups,
          relations,
        }
      : undefined,
    resourceGroups,
    relations,
    result: result
      ? {
          status: typeof result.status === "string" ? result.status : undefined,
          created: typeof result.created === "number" ? result.created : undefined,
          relationsCreated: typeof result.relationsCreated === "number" ? result.relationsCreated : undefined,
          skipped: typeof result.skipped === "number" ? result.skipped : undefined,
          failed: typeof result.failed === "number" ? result.failed : undefined,
          error: typeof result.error === "string" ? truncateText(result.error, 240) : undefined,
          structureResults: Array.isArray(result.structureResults)
            ? cloneJsonSafe(result.structureResults.slice(0, 120))
            : undefined,
          resourceResults: Array.isArray(result.resourceResults)
            ? cloneJsonSafe(result.resourceResults.slice(0, 240))
            : undefined,
          relationResults: Array.isArray(result.relationResults)
            ? cloneJsonSafe(result.relationResults.slice(0, 240))
            : undefined,
        }
      : undefined,
  };
}

function sanitizeMessage(
  message: unknown,
  maxContentLength: number,
): PlainRecord | null {
  if (!isPlainRecord(message)) {
    return null;
  }

  const next: PlainRecord = {
    id: typeof message.id === "string" ? message.id : undefined,
    type: typeof message.type === "string" ? message.type : "agent",
    content: truncateText(message.content, maxContentLength),
  };

  if (typeof message.icon === "string") {
    next.icon = message.icon;
  }
  if (typeof message.gradient === "string") {
    next.gradient = message.gradient;
  }
  if (Array.isArray(message.processBlocks)) {
    next.processBlocks = cloneJsonSafe(message.processBlocks);
  }
  if (typeof message.backendMessageId === "string") {
    next.backendMessageId = message.backendMessageId;
  }
  if (typeof message.enhancementSourceMessageId === "string") {
    next.enhancementSourceMessageId = message.enhancementSourceMessageId;
  }
  if (message.disposalOperation && isPlainRecord(message.disposalOperation)) {
    next.disposalOperation = cloneJsonSafe(message.disposalOperation);
  }
  if (message.alarmAnalystCard && isPlainRecord(message.alarmAnalystCard)) {
    next.alarmAnalystCard = cloneJsonSafe(message.alarmAnalystCard);
  }
  if (Array.isArray(message.workorders)) {
    next.workorders = cloneJsonSafe(message.workorders);
  }
  if (isPlainRecord(message.resourceImportFlow)) {
    next.resourceImportFlow = sanitizeResourceImportFlow(message.resourceImportFlow);
  }

  return next;
}

function sanitizeMessages(messages: unknown[], maxContentLength: number) {
  return messages
    .slice(-MAX_MESSAGES_PER_SESSION)
    .map((message) => sanitizeMessage(message, maxContentLength))
    .filter((message): message is PlainRecord => Boolean(message));
}

function sanitizeSession(
  session: unknown,
  {
    maxMessages,
    maxContentLength,
  }: { maxMessages: number; maxContentLength: number },
): PlainRecord | null {
  if (!isPlainRecord(session)) {
    return null;
  }

  const rawMessages = Array.isArray(session.messages) ? session.messages : [];
  const messages = rawMessages
    .slice(-maxMessages)
    .map((message) => sanitizeMessage(message, maxContentLength))
    .filter((message): message is PlainRecord => Boolean(message));

  return {
    id:
      typeof session.id === "string"
        ? session.id
        : `session-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    employeeId: typeof session.employeeId === "string" ? session.employeeId : "",
    title:
      typeof session.title === "string"
        ? truncateText(session.title, 120)
        : `会话 · ${new Date().toLocaleString("zh-CN")}`,
    createdAt:
      typeof session.createdAt === "string" ? session.createdAt : new Date().toISOString(),
    updatedAt:
      typeof session.updatedAt === "string" ? session.updatedAt : new Date().toISOString(),
    messages,
    sessionId: typeof session.sessionId === "string" ? session.sessionId : undefined,
    status: typeof session.status === "string" ? session.status : undefined,
    detail: typeof session.detail === "string" ? truncateText(session.detail, 240) : undefined,
    tag: typeof session.tag === "string" ? truncateText(session.tag, 40) : undefined,
    meta: isPlainRecord(session.meta) ? cloneJsonSafe(session.meta) : undefined,
  };
}

function normalizeConversationStore(
  value: unknown,
  {
    maxSessionsPerEmployee = MAX_SESSIONS_PER_EMPLOYEE,
    maxMessagesPerSession = MAX_MESSAGES_PER_SESSION,
    maxMessageContentLength = MAX_MESSAGE_CONTENT_LENGTH,
  }: {
    maxSessionsPerEmployee?: number;
    maxMessagesPerSession?: number;
    maxMessageContentLength?: number;
  } = {},
): ConversationStore {
  if (!isPlainRecord(value)) {
    return {};
  }

  return Object.fromEntries(
    Object.entries(value).map(([key, sessions]) => {
      const normalizedSessions = (Array.isArray(sessions) ? sessions : [])
        .slice(0, maxSessionsPerEmployee)
        .map((session) =>
          sanitizeSession(session, {
            maxMessages: maxMessagesPerSession,
            maxContentLength: maxMessageContentLength,
          }),
        )
        .filter((session): session is PlainRecord => Boolean(session));

      return [key, normalizedSessions];
    }),
  );
}

export function loadConversationStore(): ConversationStore {
  try {
    for (const legacyKey of LEGACY_STORAGE_KEYS) {
      window.localStorage.removeItem(legacyKey);
    }
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? normalizeConversationStore(JSON.parse(raw)) : {};
  } catch {
    return {};
  }
}

export function saveConversationStore(store: ConversationStore): void {
  const normalized = normalizeConversationStore(store);

  try {
    for (const legacyKey of LEGACY_STORAGE_KEYS) {
      window.localStorage.removeItem(legacyKey);
    }
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
    return;
  } catch (error) {
    if (!(error instanceof DOMException) || error.name !== "QuotaExceededError") {
      console.error("Failed to persist conversation store:", error);
      return;
    }
  }

  try {
    const fallbackStore = normalizeConversationStore(store, {
      maxSessionsPerEmployee: FALLBACK_SESSIONS_PER_EMPLOYEE,
      maxMessagesPerSession: FALLBACK_MESSAGES_PER_SESSION,
      maxMessageContentLength: FALLBACK_MESSAGE_CONTENT_LENGTH,
    });
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(fallbackStore));
  } catch (fallbackError) {
    console.warn("Conversation store exceeded localStorage quota; clearing persisted cache.", fallbackError);
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  }
}

export function createConversationSession(
  employee: { id: string; name: string },
  initialMessages: unknown[],
) {
  const now = new Date().toISOString();
  return {
    id: `session-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    employeeId: employee.id,
    title: `${employee.name} · ${new Date().toLocaleString("zh-CN")}`,
    createdAt: now,
    updatedAt: now,
    messages: sanitizeMessages(
      Array.isArray(initialMessages) ? initialMessages : [],
      MAX_MESSAGE_CONTENT_LENGTH,
    ),
  };
}
