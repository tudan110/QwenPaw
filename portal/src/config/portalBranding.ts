const DEFAULT_PORTAL_APP_TITLE = "数字员工门户";

function normalizeAppTitle(value: string | undefined): string | undefined {
  const trimmedValue = value?.trim();
  return trimmedValue ? trimmedValue : undefined;
}

export const portalAppTitle =
  normalizeAppTitle(window.__PORTAL_RUNTIME_CONFIG__?.appTitle) ??
  normalizeAppTitle(import.meta.env.VITE_PORTAL_APP_TITLE) ??
  DEFAULT_PORTAL_APP_TITLE;

export function applyPortalDocumentTitle() {
  document.title = portalAppTitle;
}
