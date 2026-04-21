const DEFAULT_PORTAL_APP_TITLE = "数字员工门户";
const DEFAULT_PORTAL_GATEWAY_AGENT_ID = "gateway";
const DEFAULT_PORTAL_GATEWAY_PROVIDER_ID = "ctyun";
const DEFAULT_PORTAL_GATEWAY_MODEL_ID = "Qwen3.5-397B-A17B";

function normalizeAppTitle(value: string | undefined): string | undefined {
  const trimmedValue = value?.trim();
  return trimmedValue ? trimmedValue : undefined;
}

function normalizeAgentId(value: string | undefined): string | undefined {
  const trimmedValue = value?.trim();
  return trimmedValue ? trimmedValue : undefined;
}

export const portalAppTitle =
  normalizeAppTitle(window.__PORTAL_RUNTIME_CONFIG__?.appTitle) ??
  normalizeAppTitle(import.meta.env.VITE_PORTAL_APP_TITLE) ??
  DEFAULT_PORTAL_APP_TITLE;

export const portalGatewayAgentId =
  normalizeAgentId(window.__PORTAL_RUNTIME_CONFIG__?.gatewayAgentId) ??
  normalizeAgentId(import.meta.env.VITE_PORTAL_GATEWAY_AGENT_ID) ??
  DEFAULT_PORTAL_GATEWAY_AGENT_ID;

export const portalGatewayDefaultProviderId =
  normalizeAgentId(window.__PORTAL_RUNTIME_CONFIG__?.gatewayDefaultProviderId) ??
  normalizeAgentId(import.meta.env.VITE_PORTAL_GATEWAY_DEFAULT_PROVIDER_ID) ??
  DEFAULT_PORTAL_GATEWAY_PROVIDER_ID;

export const portalGatewayDefaultModelId =
  normalizeAgentId(window.__PORTAL_RUNTIME_CONFIG__?.gatewayDefaultModelId) ??
  normalizeAgentId(import.meta.env.VITE_PORTAL_GATEWAY_DEFAULT_MODEL_ID) ??
  DEFAULT_PORTAL_GATEWAY_MODEL_ID;

export function applyPortalDocumentTitle() {
  document.title = portalAppTitle;
}
