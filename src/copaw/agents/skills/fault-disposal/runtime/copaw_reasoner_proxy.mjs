import { Buffer } from "node:buffer";

function isMissingAgentResponse(status, text) {
  return status === 404 && /Agent\s+['"].+['"]\s+not\s+found/i.test(text || "");
}

function buildAgentHeaders(agentId, extraHeaders = {}) {
  return {
    ...(agentId ? { "X-Agent-Id": agentId } : {}),
    ...extraHeaders,
  };
}

function parseSseChunk(chunk) {
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

function extractCompletedTextFromMessage(event) {
  const content = Array.isArray(event?.content) ? event.content : [];
  let text = "";
  for (const item of content) {
    if (item?.type === "text" && item?.text) {
      text += String(item.text);
    }
  }
  return text;
}

async function readSseResponse(response, { onDelta } = {}) {
  if (!response.body) {
    throw new Error("CoPAW stream body is empty");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let assistantText = "";

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
        throw new Error(String(event.error));
      }

      if (
        event.object === "content" &&
        event.type === "text" &&
        event.delta === true &&
        event.text
      ) {
        const text = String(event.text);
        assistantText += text;
        onDelta?.(text);
        continue;
      }

      if (
        event.object === "message" &&
        event.role === "assistant" &&
        event.type === "message" &&
        event.status === "completed" &&
        !assistantText.trim()
      ) {
        assistantText += extractCompletedTextFromMessage(event);
      }
    }
  }

  const finalEvent = parseSseChunk(buffer);
  if (finalEvent?.error) {
    throw new Error(String(finalEvent.error));
  }

  if (
    finalEvent &&
    finalEvent.object === "message" &&
    finalEvent.role === "assistant" &&
    finalEvent.type === "message" &&
    finalEvent.status === "completed" &&
    !assistantText.trim()
  ) {
    assistantText += extractCompletedTextFromMessage(finalEvent);
  }

  return assistantText;
}

async function ensureCopawChat({ baseUrl, agentId, chatSpec }) {
  if (!chatSpec?.session_id || !chatSpec?.user_id) {
    return null;
  }

  const searchParams = new URLSearchParams({
    user_id: String(chatSpec.user_id),
    channel: String(chatSpec.channel || "console"),
  });
  const listResponse = await fetch(`${baseUrl}/chats?${searchParams.toString()}`, {
    method: "GET",
    headers: buildAgentHeaders(agentId),
  });
  if (!listResponse.ok) {
    const text = await listResponse.text().catch(() => "");
    throw new Error(text || `CoPAW chats query failed: ${listResponse.status}`);
  }

  const chats = await listResponse.json().catch(() => []);
  const existingChat = Array.isArray(chats)
    ? chats.find((chat) => chat?.session_id === chatSpec.session_id)
    : null;
  if (existingChat) {
    return existingChat;
  }

  const createResponse = await fetch(`${baseUrl}/chats`, {
    method: "POST",
    headers: buildAgentHeaders(agentId, {
      "Content-Type": "application/json",
    }),
    body: JSON.stringify(chatSpec),
  });
  if (!createResponse.ok) {
    const text = await createResponse.text().catch(() => "");
    throw new Error(text || `CoPAW chat create failed: ${createResponse.status}`);
  }
  return createResponse.json().catch(() => null);
}

async function requestCopawOnce({
  baseUrl,
  agentId,
  requestPayload,
  chatSpec,
  timeoutMs,
  streamJsonl,
}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    let chat = null;
    try {
      chat = await ensureCopawChat({
        baseUrl,
        agentId,
        chatSpec,
      });
    } catch (error) {
      const message = String(error?.message || error || "");
      return {
        ok: false,
        status: isMissingAgentResponse(404, message) ? 404 : 0,
        text: message,
      };
    }
    const response = await fetch(`${baseUrl}/console/chat`, {
      method: "POST",
      headers: buildAgentHeaders(agentId, {
        "Content-Type": "application/json",
      }),
      body: JSON.stringify(requestPayload),
      signal: controller.signal,
    });

    if (!response.ok) {
      const text = await response.text();
      return {
        ok: false,
        status: response.status,
        text,
      };
    }

    const assistantText = await readSseResponse(response, {
      onDelta: streamJsonl
        ? (text) => {
            process.stdout.write(
              `${JSON.stringify({ type: "delta", text })}\n`,
            );
          }
        : undefined,
    });

    return {
      ok: true,
      agentId,
      chatId: chat?.id || null,
      text: assistantText,
    };
  } finally {
    clearTimeout(timer);
  }
}

async function main() {
  const payloadBase64Index = process.argv.indexOf("--payload-base64");
  if (payloadBase64Index < 0 || !process.argv[payloadBase64Index + 1]) {
    throw new Error("Missing --payload-base64");
  }

  const streamJsonl = process.argv.includes("--stream-jsonl");
  const payload = JSON.parse(
    Buffer.from(process.argv[payloadBase64Index + 1], "base64").toString("utf8"),
  );

  const { baseUrl, agentCandidates, requestPayload, chatSpec, timeoutMs = 90000 } = payload;
  let lastError = "";

  for (const agentId of agentCandidates || []) {
    const result = await requestCopawOnce({
      baseUrl,
      agentId,
      requestPayload,
      chatSpec,
      timeoutMs,
      streamJsonl,
    });

    if (!result.ok) {
      lastError = result.text || `HTTP ${result.status}`;
      if (isMissingAgentResponse(result.status, result.text)) {
        continue;
      }
      throw new Error(lastError);
    }

    const output = {
      type: "done",
      usedAgentId: result.agentId,
      chatId: result.chatId,
      text: result.text,
    };

    if (streamJsonl) {
      process.stdout.write(`${JSON.stringify(output)}\n`);
    } else {
      process.stdout.write(JSON.stringify(output, null, 2));
    }
    return;
  }

  throw new Error(lastError || "CoPAW reasoner proxy request failed");
}

main().catch((error) => {
  process.stderr.write(String(error?.message || error));
  process.exit(1);
});
