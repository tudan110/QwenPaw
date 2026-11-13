import {
  clearAuthToken,
  getApiToken,
  getApiUrl,
  setAuthToken,
  captureAuthState,
  isAuthStateCurrent,
} from "./config";

/** Authenticate before PluginProvider or any other business API mounts. */
export async function bootstrapSso(): Promise<
  "ready" | "redirect" | "unavailable" | "signed-out"
> {
  if (new URL(window.location.href).searchParams.get("signed_out") === "1") {
    return "signed-out";
  }
  try {
    let snapshot = captureAuthState();
    const signedOut = () =>
      new URL(window.location.href).searchParams.get("signed_out") === "1";
    const current = () => isAuthStateCurrent(snapshot) && !signedOut();
    const superseded = () =>
      signedOut() || !getApiToken()
        ? ("signed-out" as const)
        : ("unavailable" as const);
    const status = await fetch(getApiUrl("/portal/sso/status"), {
      signal: AbortSignal.timeout(10_000),
    });
    if (!current()) return superseded();
    if (!status.ok) return "unavailable";
    const config = await status.json();
    if (!current()) return superseded();
    if (!config.sso_required) return "ready";
    const stored = getApiToken();
    const verified = await fetch(getApiUrl("/portal/sso/session"), {
      headers: stored.startsWith("qp1.")
        ? { Authorization: `Bearer ${stored}` }
        : {},
      signal: AbortSignal.timeout(10_000),
    });
    if (!current()) return superseded();
    if (verified.ok) {
      const result = await verified.json();
      if (!current()) return superseded();
      if (
        typeof result.access_token === "string" &&
        result.access_token.startsWith("qp1.")
      ) {
        setAuthToken(result.access_token);
        return "ready";
      }
      if (result.token_kind !== "inoe") return "unavailable";
    } else {
      if (verified.status !== 401) return "unavailable";
      clearAuthToken();
      snapshot = captureAuthState();
    }
    const login = await fetch(getApiUrl("/portal/sso/token-login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
      signal: AbortSignal.timeout(20_000),
    });
    if (!current()) return superseded();
    if (login.ok) {
      const result = await login.json();
      if (!current()) return superseded();
      if (
        typeof result.access_token !== "string" ||
        !result.access_token.startsWith("qp1.")
      ) {
        return "unavailable";
      }
      setAuthToken(result.access_token);
      return "ready";
    }
    if (login.status !== 401) return "unavailable";
    const url = new URL(
      config.login_url ||
        `${window.location.protocol}//${window.location.hostname}:30081/login`,
      window.location.href,
    );
    if (!["http:", "https:"].includes(url.protocol)) return "unavailable";
    url.searchParams.set("redirect", window.location.href);
    window.location.assign(url.toString());
    return "redirect";
  } catch {
    console.error("SSO bootstrap failed");
    return "unavailable";
  }
}
