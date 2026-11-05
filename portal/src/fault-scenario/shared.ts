export type FaultScenarioTheme = "light" | "dark";

export interface FaultScenarioDiagnosisRequest {
  sessionId: string;
  employeeId: string;
  content: string;
  [key: string]: unknown;
}

export interface FaultScenarioStep {
  id?: string;
  status?: string;
}

export interface FaultScenarioLogEntry {
  stage?: string;
  summary?: string;
}

export interface FaultScenarioRootCause {
  type?: string;
  object?: string;
}

export interface FaultScenarioAction {
  // Lightweight action shape; backend/front-end currently produce varied action objects.
  // Extend this with specific fields when a stronger contract exists.
  [key: string]: unknown;
}

export interface ManualOperationGuide {
  source: "cmdb-only";
  executionMode: "manual-only";
  deploymentKind: "kubernetes" | "docker" | "host" | "unknown";
  deploymentConfirmed: boolean;
  relatedPlatforms: Array<{ id: string; name: string; type: string }>;
  knownParameters: Record<string, string>;
  missingParameters: string[];
  markdown: string;
}

export interface FaultScenarioResult {
  summary?: string;
  rootCause?: FaultScenarioRootCause;
  steps?: FaultScenarioStep[];
  logEntries?: FaultScenarioLogEntry[];
  actions?: FaultScenarioAction[];
  manualGuide?: ManualOperationGuide | null;
}

export function getManualOperationGuide(
  guide?: ManualOperationGuide | null,
): ManualOperationGuide | null {
  if (guide == null) return null;
  if (
    guide.source !== "cmdb-only" ||
    guide.executionMode !== "manual-only" ||
    typeof guide.markdown !== "string" ||
    !guide.markdown.trim()
  ) {
    throw new Error("人工操作指南协议无效，不能作为自动执行动作展示。");
  }
  return guide;
}

export interface FaultScenarioDiagnosisResponse {
  result?: FaultScenarioResult;
}

export function getFaultScenarioResult(
  response?: FaultScenarioDiagnosisResponse | null,
): FaultScenarioResult | undefined {
  return response?.result;
}

export function getFaultScenarioSummary(result?: FaultScenarioResult | null) {
  return result?.summary || "已完成关联分析。";
}

export function getFaultScenarioDrawerClassName(theme: FaultScenarioTheme = "light") {
  return theme === "dark"
    ? "fault-scenario-log-drawer theme-dark"
    : "fault-scenario-log-drawer";
}
