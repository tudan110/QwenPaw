// Map a conversation "process record" block to a generic activity category.
//
// The live chat (digital-employee) streams process blocks (thinking / tool /
// response). For tool & thinking steps we expose ONLY a coarse "what is it
// doing" category — never the tool/skill name, arguments, script body, or raw
// reasoning text. Those details stay server-side and in the Traces Center.

export type TraceStepBlock = {
  kind?: string;
  title?: string;
  icon?: string;
};

export type TraceStepDisplay = { icon: string; text: string };

const VERB_CATEGORIES: Array<{ text: string; verbs: string[] }> = [
  {
    text: "执行脚本",
    verbs: ["shell", "bash", "sh", "zsh", "terminal", "python", "script", "exec", "execute", "run", "cmd", "command", "powershell"],
  },
  {
    text: "检索数据",
    verbs: ["search", "query", "web", "browse", "crawl", "http", "fetch", "request", "retrieve", "lookup", "grep", "find", "scan"],
  },
  {
    text: "读取数据",
    verbs: ["read", "list", "ls", "get", "load", "describe", "count", "stat", "show", "view", "inspect", "detail", "info", "cat", "tail", "head"],
  },
  {
    text: "生成内容",
    verbs: ["write", "create", "generate", "render", "report", "export", "draw", "chart", "plot", "compose", "build", "make", "save", "edit", "patch", "modify", "update"],
  },
];

/** Split a raw tool name (supporting snake_case, kebab-case, camelCase, and MCP namespaces `__`) into lower-cased tokens. */
function tokenizeToolName(raw: string): { tokens: string[]; actionTokens: string[] } {
  const parts = raw.split("__");
  const actionPart = parts.length > 1 ? parts[parts.length - 1] : raw;

  const splitCamelAndSeparators = (s: string) =>
    s
      .replace(/([a-z0-9])([A-Z])/g, "$1_$2") // camelCase -> camel_Case
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .filter(Boolean);

  return {
    tokens: splitCamelAndSeparators(raw),
    actionTokens: splitCamelAndSeparators(actionPart),
  };
}

/** Coarse category for the entire process-record step summary header. */
export function traceStepDisplay(block: TraceStepBlock | null | undefined): TraceStepDisplay {
  if (block?.kind === "thinking") {
    return { icon: "fa-brain", text: "思考分析" };
  }
  if (block?.kind === "tool") {
    const raw = String(block?.title || "").trim();
    if (!raw) {
      return { icon: "fa-puzzle-piece", text: "调用技能" };
    }

    const { tokens } = tokenizeToolName(raw);

    if (tokens.includes("skill") || tokens.includes("skills")) {
      return { icon: "fa-puzzle-piece", text: "调用技能" };
    }

    return { icon: "fa-screwdriver-wrench", text: "调用工具" };
  }
  return { icon: block?.icon || "fa-gear", text: "处理中" };
}

/** Detailed coarse action category for a specific tool execution (shown in the expanded details row). */
export function getToolActionCategory(rawTitle: string | null | undefined): string {
  const raw = String(rawTitle || "").trim();
  if (!raw) return "调用工具";

  const { tokens, actionTokens } = tokenizeToolName(raw);

  if (tokens.includes("skill") || tokens.includes("skills")) {
    return "调用技能";
  }

  // Explicit script execution hints anywhere in tokens
  if (tokens.some((t) => ["shell", "bash", "python", "script", "terminal", "powershell"].includes(t))) {
    return "执行脚本";
  }

  const candidateTokensList = [actionTokens, tokens];

  for (const tokenList of candidateTokensList) {
    const first = tokenList[0];
    if (!first) continue;

    for (const cat of VERB_CATEGORIES) {
      if (cat.verbs.includes(first)) {
        return cat.text;
      }
    }
  }

  return "调用工具";
}



