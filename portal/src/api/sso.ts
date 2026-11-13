// Portal SSO API calls. Reuses requestPortalApi so the same /portal-api ->
// /api/portal base-URL resolution + same-origin fallback applies. Paths here
// are relative to /api/portal, and the SSO router mounts under /sso.

import type { SsoUser } from "../auth/ssoSession";
import { requestPortalApi } from "./portalWorkorders";

export interface SsoExchangeResult {
  access_token: string;
  token_type: string;
  token_kind?: "qwenpaw";
  expires_in_seconds: number;
  scope?: string | null;
  user: SsoUser;
}

async function requestSsoApi<T>(
  path: string,
  init: RequestInit,
  timeoutMs = 10_000,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await requestPortalApi<T>(path, {
      ...init,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Token pass-through login: validate an existing INOE login token.
 *
 * Pass the token explicitly, or omit it to let the backend read the
 * Cnos-Inoe-Admin-Token cookie (works when portal shares INOE's hostname).
 */
export async function tokenLogin(
  token?: string | null,
): Promise<SsoExchangeResult> {
  return requestSsoApi<SsoExchangeResult>("/sso/token-login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(token ? { token } : {}),
  });
}

export async function clearSsoLoginCookie(): Promise<{ cleared: boolean }> {
  return requestSsoApi<{ cleared: boolean }>(
    "/sso/clear-login-cookie",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
      keepalive: true,
    },
    2_000,
  );
}

/** Trade the one-time authorization code for portal login material. */
export async function exchangeSsoCode(
  code: string,
  state?: string | null,
): Promise<SsoExchangeResult> {
  return requestPortalApi<SsoExchangeResult>("/sso/exchange", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, state: state ?? "" }),
  });
}

/** Whether the backend has the credentials to perform an exchange. */
export async function getSsoStatus(): Promise<{ configured: boolean }> {
  return requestPortalApi<{ configured: boolean }>("/sso/status");
}
