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
  if (message.disposalOperation && isPlainRecord(message.disposalOperation)) {
    next.disposalOperation = cloneJsonSafe(message.disposalOperation);
  }
  if (Array.isArray(message.workorders)) {
    next.workorders = cloneJsonSafe(message.workorders);
  }
  if (isPlainRecord(message.resourceImportFlow)) {
    next.resourceImportFlow = cloneJsonSafe(message.resourceImportFlow);
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
