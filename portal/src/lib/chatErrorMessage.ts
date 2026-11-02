// Turn backend chat/stream errors into safe, user-friendly text.
//
// End users must never see raw tracebacks, internal temp-dump paths
// (e.g. "(Details: /tmp/qwenpaw_query_error_xxx.json)"), internal
// product/package names, or raw provider error codes. We map known error
// categories to friendly Chinese messages and, for everything else, fall back
// to a single generic friendly line rather than echoing the raw error.

// Generic, always-safe fallback shown when we can't (or shouldn't) say more.
const GENERIC_FRIENDLY = "服务暂时遇到点问题，请稍后重试。";

// Stack-trace signatures (Python / JS) that must never reach end users.
const TRACEBACK_PATTERN =
  /Traceback \(most recent call last\)|File "[^"]+", line \d+|\n\s*at [\w.$<>]+ \(/i;

const KUNLUN_ERROR_MESSAGES: Record<string, string> = {
  KUNLUN_MODEL_UNAUTHORIZED:
    "昆仑模型未授权：当前调用身份无权使用所选模型。请联系管理员核对模型 ID、应用授权及模型密钥权限。",
  KUNLUN_ROUTE_NOT_FOUND:
    "昆仑接口未找到：网关未找到对应的模型接口。请联系管理员核对接口地址和网关转发路由。",
  KUNLUN_NOT_FOUND:
    "昆仑接口或模型未找到：请联系管理员核对所选模型 ID、接口地址和网关转发路由。",
  KUNLUN_AUTH_FAILED:
    "昆仑身份验证未通过：请联系管理员检查网关凭据和后端模型密钥是否有效；这不一定代表凭据已过期。",
  KUNLUN_NOT_CONFIGURED:
    "昆仑调用配置不完整：请联系管理员补全网关地址及调用凭据。",
  KUNLUN_SERVICE_UNAVAILABLE:
    "昆仑网关或模型服务暂时不可用。请稍后重试；持续失败时，请联系管理员检查网关及模型服务状态。",
  KUNLUN_CONNECTION_FAILED:
    "无法连接昆仑服务。请联系管理员检查服务器到网关的网络连接；如需 SDP，请确认其登录状态和资源访问权限。",
  KUNLUN_TIMEOUT:
    "昆仑服务响应超时，本轮未能完成回答。请稍后重试；持续超时时，请联系管理员检查网关和模型服务。",
  KUNLUN_RATE_LIMITED:
    "昆仑请求受限：请求频率或调用额度超出限制。请稍后重试，或联系管理员核对调用额度。",
};

/**
 * Normalize whatever the runtime hands us — a plain string, an
 * `IAgentScopeRuntimeError` (`{ code, message }`), or an ERROR message item
 * (`{ code, message, content: [...] }`) — into a single raw string that
 * {@link toFriendlyChatError} can categorize. The non-sensitive `code` token is
 * appended so category mapping can still key on it.
 */
export function extractRuntimeErrorText(errorLike: unknown): string {
  if (errorLike == null) return "";
  if (typeof errorLike === "string") return errorLike;
  if (typeof errorLike !== "object") return String(errorLike);

  const obj = errorLike as Record<string, unknown>;
  const parts: string[] = [];

  if (typeof obj.message === "string" && obj.message.trim()) {
    parts.push(obj.message.trim());
  }
  if (Array.isArray(obj.content)) {
    for (const item of obj.content) {
      const text = (item as { text?: unknown } | null)?.text;
      if (typeof text === "string" && text.trim()) {
        parts.push(text.trim());
      }
    }
  }

  let text = parts.join(" ").trim();
  const code = typeof obj.code === "string" ? obj.code.trim() : "";
  if (code && !text.includes(code)) {
    text = text ? `${text} (${code})` : code;
  }
  return text;
}

export function toFriendlyChatError(error: unknown): string {
  const raw = String(
    (error as { message?: unknown } | null)?.message ??
      (typeof error === "string" ? error : ""),
  ).trim();

  if (!raw) {
    return GENERIC_FRIENDLY;
  }

  // 明确的堆栈/崩溃特征：直接给通用友好提示，绝不外泄原始内容。
  if (TRACEBACK_PATTERN.test(raw)) {
    return GENERIC_FRIENDLY;
  }

  const kunlunCode = raw.match(/\bKUNLUN_[A-Z_]+\b/)?.[0];
  if (
    kunlunCode &&
    Object.prototype.hasOwnProperty.call(KUNLUN_ERROR_MESSAGES, kunlunCode)
  ) {
    return KUNLUN_ERROR_MESSAGES[kunlunCode];
  }

  // 网络 / 流式连接中断
  if (
    /RemoteProtocolError|incomplete chunked read|peer closed connection|流式连接超时|未返回可读取的流式数据/i.test(
      raw,
    )
  ) {
    return "模型流式连接中断，请重试当前步骤。";
  }

  // vLLM rejects automatic tool calls unless its serving flags and parser are
  // configured. This signature points to model deployment configuration,
  // rather than a transient model execution failure.
  if (
    /(?:(?:["']?auto["']?|automatic)\s+tool\s+choice.{0,120}requires|requires.{0,120}(?:["']?auto["']?|automatic)\s+tool\s+choice|--enable-auto-tool-choice|--tool-call-parser)/i.test(
      raw,
    )
  ) {
    return "模型部署配置问题：vLLM 服务未启用工具调用支持，无法处理当前请求。请模型服务管理员检查启动参数 --enable-auto-tool-choice 和 --tool-call-parser；如果模型服务已启用，请平台管理员检查该模型的工具调用配置。反馈问题时请附模型名称和发生时间。";
  }

  // 模型执行类错误：按类别给出友好提示，隐藏内部实现细节
  // （临时文件路径、错误码、内部名称）。
  const looksLikeModelError =
    /execution of model|MODEL_EXECUTION|MODEL_TIMEOUT|MODEL_QUOTA|UNAUTHORIZED_MODEL|CONTEXT_LENGTH|qwenpaw_query_error|[（(]\s*Details:/i.test(
      raw,
    );

  if (looksLikeModelError) {
    if (/timeout|timed out|MODEL_TIMEOUT|超时/i.test(raw)) {
      return "模型响应超时，请稍后重试。";
    }
    if (/quota|rate limit|too many requests|MODEL_QUOTA/i.test(raw)) {
      return "当前访问量较大，请稍后重试。";
    }
    if (/context|too many tokens|CONTEXT_LENGTH/i.test(raw)) {
      return "本轮对话内容过长，请精简后重试。";
    }
    if (/unauthorized|authentication|api key|UNAUTHORIZED/i.test(raw)) {
      return "模型服务暂不可用，请联系管理员。";
    }
    return "模型服务暂时不可用，请稍后重试。";
  }

  // 兜底：绝不回显原始错误（可能含堆栈/内部路径），统一给友好提示。
  return GENERIC_FRIENDLY;
}

/** Convenience: normalize a runtime error object/string, then friendly-map it. */
export function runtimeErrorToFriendly(errorLike: unknown): string {
  return toFriendlyChatError(extractRuntimeErrorText(errorLike));
}
