import { requestPortalApi } from "./portalWorkorders";

export type CapabilityKind = "skill" | "mcp";
export type CapabilityChange = "default" | "revoked" | "temporary";
export interface AgentCapability {
  kind: CapabilityKind;
  name: string;
  configured: boolean;
  workspace_state?: "active" | "disabled" | "inactive" | "error";
  mode: "inherited" | "ask" | "revoked" | "temporary";
  expires_at: number | null;
}
export interface AgentAccessBoundary {
  production_guards: boolean;
  mcp_policy: "off" | "invalid" | "host" | "exact";
  mcp_endpoint_count?: number;
}
export interface AgentConsent {
  id: string;
  service: string;
  tool: string;
  expires: number;
}

const endpoint = "/agent-permissions";

export function listAgentPermissions(agentId: string, signal?: AbortSignal) {
  return requestPortalApi<{ agent_id: string; items: AgentCapability[]; access_boundary?: AgentAccessBoundary }>(endpoint, {
    signal, headers: { "X-Agent-Id": agentId },
  });
}

export function setAgentPermission(agentId: string, item: AgentCapability, mode: CapabilityChange) {
  return requestPortalApi(endpoint, {
    method: "POST",
    headers: { "X-Agent-Id": agentId, "Content-Type": "application/json" },
    body: JSON.stringify({ kind: item.kind, name: item.name, mode }),
  });
}

export function listAgentConsent(agentId: string, sessionId: string, signal?: AbortSignal) {
  return requestPortalApi<{ items: AgentConsent[] }>(
    `${endpoint}/requests?${new URLSearchParams({ session_id: sessionId })}`, {
      signal, headers: { "X-Agent-Id": agentId },
    }, 5000,
  );
}

export function resolveAgentConsent(agentId: string, sessionId: string, requestId: string, decision: "allow" | "deny") {
  return requestPortalApi(`${endpoint}/requests/${encodeURIComponent(requestId)}`, {
    method: "POST",
    headers: { "X-Agent-Id": agentId, "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, decision }),
  });
}
