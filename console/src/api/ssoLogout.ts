import { clearAuthToken, getApiToken, getApiUrl } from "./config";

/** Complete server revocation before dropping the credential used to retry. */
export async function logoutConsole(ssoEnabled: boolean): Promise<void> {
  if (ssoEnabled) {
    const token = getApiToken();
    const response = await fetch(getApiUrl("/portal/sso/logout"), {
      method: "POST",
      credentials: "include",
      headers: token.startsWith("qp1.")
        ? { Authorization: `Bearer ${token}` }
        : {},
      signal: AbortSignal.timeout(10_000),
    });
    if (response.status === 401) {
      const cleanup = await fetch(getApiUrl("/portal/sso/clear-login-cookie"), {
        method: "POST",
        credentials: "include",
        signal: AbortSignal.timeout(10_000),
      });
      if (!cleanup.ok || (await cleanup.json()).cleared !== true)
        throw new Error("退出未完成，请重试。");
    } else if (!response.ok || (await response.json()).logged_out !== true) {
      throw new Error("退出未完成，请重试。");
    }
  }
  clearAuthToken();
  // A still-valid upstream INOE cookie must not silently undo an explicit
  // application logout. The landing screen requires an explicit sign-in.
  const destination = new URL(window.location.href);
  destination.searchParams.set("signed_out", "1");
  window.location.assign(destination.toString());
}
