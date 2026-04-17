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

export interface FaultScenarioResult {
  summary?: string;
  rootCause?: FaultScenarioRootCause;
  steps?: FaultScenarioStep[];
  logEntries?: FaultScenarioLogEntry[];
  actions?: FaultScenarioAction[];
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
