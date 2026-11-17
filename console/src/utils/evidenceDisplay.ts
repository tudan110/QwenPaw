/** Presentation only. Never feed the masked result back into execution/config. */
export function endpointOrigin(value: string): string {
  try {
    const url = new URL(value);
    return `${url.protocol}//${url.host}`;
  } catch {
    return "[hidden]";
  }
}

function approvalUrl(value: string): string {
  try {
    const url = new URL(value);
    // The path can determine the approval scope. Keep it visible while
    // dropping embedded credentials, query values and fragments.
    return `${url.protocol}//${url.host}${url.pathname}${
      url.search ? "?[hidden]" : ""
    }${url.hash ? "#[hidden]" : ""}`;
  } catch {
    return "[hidden]";
  }
}

export function safeDisplayText(value: string): string {
  return value
    .replace(
      /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g,
      "[hidden]",
    )
    .replace(/[a-zA-Z][a-zA-Z0-9+.-]*:\/\/[^\s<>"']+/g, approvalUrl)
    .replace(/\b(?:Bearer|Basic)\s+\S+/gi, "[hidden]")
    .replace(
      /([\w-]*(?:token|password|passwd|secret|api[_-]?key|access[_-]?key|credential|cookie|authorization)[\w-]*["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)/gi,
      "$1[hidden]",
    )
    .replace(
      /(--?[\w-]*(?:token|password|passwd|secret|api[_-]?key|access[_-]?key|credential)[\w-]*\s+)(?:"[^"]*"|'[^']*'|\S+)/gi,
      "$1[hidden]",
    )
    .replace(/\b(?:sk-|gh[pousr]_)[A-Za-z0-9_-]{16,}/g, "[hidden]")
    .replace(
      /\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g,
      "[hidden]",
    );
}

export function redactForDisplay(value: unknown, depth = 0): unknown {
  if (depth > 12) return "[hidden]";
  if (typeof value === "string") return safeDisplayText(value);
  if (Array.isArray(value))
    return value.map((item) => redactForDisplay(item, depth + 1));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        /(?:token|password|passwd|secret|credential|cookie|authorization|api.?key|access.?key|private.?key|headers|^env$)/i.test(
          key,
        )
          ? "[hidden]"
          : redactForDisplay(item, depth + 1),
      ]),
    );
  }
  return value;
}

export function auditCsvCell(value: unknown): string {
  const text = String(value ?? "");
  // Spreadsheets must treat exported event text as data, not formulas.
  const escaped = /^[\s]*[=+\-@\t\r\n]/.test(text) ? `'${text}` : text;
  return `"${escaped.replace(/"/g, '""')}"`;
}
