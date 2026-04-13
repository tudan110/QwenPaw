const DEFAULT_API_BASE_URL = "/copaw-api/api";
const DEFAULT_FALLBACK_AGENT_ID = "default";

const API_BASE_URL = (import.meta.env.VITE_COPAW_API_BASE_URL || DEFAULT_API_BASE_URL).replace(
  /\/$/,
  "",
);

interface CopawRequestOptions {
  agentId?: string;
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

interface ChatListParams {
  user_id?: string;
  channel?: string;
}

interface StreamChatOptions {
  signal?: AbortSignal;
  onEvent?: (event: Record<string, any>) => void;
}

function safeJsonParse(value: string) {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function extractErrorMessage(error: unknown): string {
  if (!error) {
    return "";
  }

  if (typeof error === "string") {
    const trimmed = error.trim();
    if (!trimmed) {
      return "";
    }

    const parsed = safeJsonParse(trimmed);
    if (parsed && parsed !== error) {
      const nestedMessage = extractErrorMessage(parsed);
      if (nestedMessage) {
        return nestedMessage;
      }
    }

    return trimmed;
  }

  if (error instanceof Error) {
    return extractErrorMessage(error.message) || "请求失败";
  }

  if (Array.isArray(error)) {
    return error
      .map((item) => extractErrorMessage(item))
      .filter(Boolean)
      .join("; ");
  }

  if (typeof error === "object") {
    const record = error as Record<string, unknown>;
    return (
      extractErrorMessage(record.message) ||
      extractErrorMessage(record.detail) ||
      extractErrorMessage(record.error) ||
      extractErrorMessage(record.reason) ||
      ""
    );
  }

  return String(error);
}

function getAgentCandidates(agentId?: string) {
  const fallbackAgentId =
    import.meta.env.VITE_COPAW_FALLBACK_AGENT_ID || DEFAULT_FALLBACK_AGENT_ID;
  return [...new Set([agentId, fallbackAgentId].filter(Boolean))];
}

function isMissingAgentResponse(status: number, errorText?: string) {
  return status === 404 && /Agent\s+['"].+['"]\s+not\s+found/i.test(errorText || "");
}

async function requestCopaw<T = any>(
  path: string,
  { agentId, method = "GET", body, signal }: CopawRequestOptions = {},
): Promise<T> {
  const agentCandidates = getAgentCandidates(agentId);
  let lastErrorText = "";
  let lastStatus = 0;

  for (const candidateAgentId of agentCandidates) {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      signal,
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(candidateAgentId ? { "X-Agent-Id": candidateAgentId } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });

    if (response.ok) {
      if (response.status === 204) {
        return null;
      }
      return response.json();
    }

    lastStatus = response.status;
    lastErrorText = await response.text().catch(() => "");
    if (!isMissingAgentResponse(response.status, lastErrorText)) {
      throw new Error(
        extractErrorMessage(lastErrorText) || `CoPAW 请求失败：${response.status}`,
      );
    }
  }

  throw new Error(
    extractErrorMessage(lastErrorText) || `CoPAW 请求失败：${lastStatus}`,
  );
}

export function listChats(agentId?: string, params: ChatListParams = {}) {
  const searchParams = new URLSearchParams();
  if (params.user_id) {
    searchParams.set("user_id", params.user_id);
  }
  if (params.channel) {
    searchParams.set("channel", params.channel);
  }
  const query = searchParams.toString();
  return requestCopaw(`/chats${query ? `?${query}` : ""}`, { agentId });
}

export function createChat(agentId: string | undefined, chat: Record<string, unknown>) {
  return requestCopaw("/chats", {
    agentId,
    method: "POST",
    body: chat,
  });
}

export function getChatHistory(agentId: string | undefined, chatId: string) {
  return requestCopaw(`/chats/${encodeURIComponent(chatId)}`, {
    agentId,
  });
}

export function updateChat(
  agentId: string | undefined,
  chatId: string,
  payload: Record<string, unknown>,
) {
  return requestCopaw(`/chats/${encodeURIComponent(chatId)}`, {
    agentId,
    method: "PUT",
    body: payload,
  });
}

export function deleteChat(agentId: string | undefined, chatId: string) {
  return requestCopaw(`/chats/${encodeURIComponent(chatId)}`, {
    agentId,
    method: "DELETE",
  });
}

export function stopChat(agentId: string | undefined, chatId: string) {
  return requestCopaw(`/console/chat/stop?chat_id=${encodeURIComponent(chatId)}`, {
    agentId,
    method: "POST",
  });
}

export async function streamChat(
  agentId: string | undefined,
  payload: Record<string, unknown>,
  { signal, onEvent }: StreamChatOptions = {},
) {
  const agentCandidates = getAgentCandidates(agentId);
  let response = null;
  let lastErrorText = "";
  let lastStatus = 0;

  for (const candidateAgentId of agentCandidates) {
    const candidateResponse = await fetch(`${API_BASE_URL}/console/chat`, {
      method: "POST",
      signal,
      headers: {
        "Content-Type": "application/json",
        ...(candidateAgentId ? { "X-Agent-Id": candidateAgentId } : {}),
      },
      body: JSON.stringify(payload),
    });

    if (candidateResponse.ok) {
      response = candidateResponse;
      break;
    }

    lastStatus = candidateResponse.status;
    lastErrorText = await candidateResponse.text().catch(() => "");
    if (!isMissingAgentResponse(candidateResponse.status, lastErrorText)) {
      throw new Error(
        extractErrorMessage(lastErrorText) ||
          `CoPAW 流式请求失败：${candidateResponse.status}`,
      );
    }
  }

  if (!response) {
    throw new Error(
      extractErrorMessage(lastErrorText) || `CoPAW 流式请求失败：${lastStatus}`,
    );
  }

  if (!response.body) {
    throw new Error("CoPAW 未返回可读取的流式数据");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";

    for (const chunk of chunks) {
      const event = parseSseChunk(chunk);
      if (!event) {
        continue;
      }
      if (event.error) {
        throw new Error(
          extractErrorMessage(event.error) || "CoPAW 流式请求失败",
        );
      }
      onEvent?.(event);
    }
  }

  const finalEvent = parseSseChunk(buffer);
  if (finalEvent) {
    if (finalEvent.error) {
      throw new Error(
        extractErrorMessage(finalEvent.error) || "CoPAW 流式请求失败",
      );
    }
    onEvent?.(finalEvent);
  }
}

function parseSseChunk(chunk: string): Record<string, any> | null {
  const lines = chunk
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line.startsWith("data:"));

  if (!lines.length) {
    return null;
  }

  const data = lines.map((line) => line.slice(5).trimStart()).join("\n").trim();
  if (!data) {
    return null;
  }

  try {
    return JSON.parse(data);
  } catch {
    return null;
  }
}
