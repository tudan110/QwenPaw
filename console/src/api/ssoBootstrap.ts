import { clearAuthToken, getApiToken, getApiUrl, setAuthToken } from "./config";

/** Authenticate before PluginProvider or any other business API mounts. */
export async function bootstrapSso(): Promise<
  "ready" | "redirect" | "unavailable" | "signed-out"
> {
  if (new URL(window.location.href).searchParams.get("signed_out") === "1") {
    return "signed-out";
  }
  try {
    const status = await fetch(getApiUrl("/portal/sso/status"), {
      signal: AbortSignal.timeout(10_000),
    });
    if (!status.ok) return "unavailable";
    const config = await status.json();
    if (!config.sso_required) return "ready";
    const stored = getApiToken();
    const verified = await fetch(getApiUrl("/portal/sso/session"), {
      headers: stored.startsWith("qp1.")
        ? { Authorization: `Bearer ${stored}` }
        : {},
      signal: AbortSignal.timeout(10_000),
    });
    if (verified.ok) {
      const result = await verified.json();
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
    }
    const login = await fetch(getApiUrl("/portal/sso/token-login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
      signal: AbortSignal.timeout(20_000),
    });
    if (login.ok) {
      const result = await login.json();
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
  } catch (error) {
    console.error("SSO bootstrap failed:", error);
    return "unavailable";
  }
}
