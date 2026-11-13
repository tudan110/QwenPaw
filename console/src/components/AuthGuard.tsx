import { useEffect, useState, type ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { authApi } from "../api/modules/auth";
import {
  getApiUrl,
  getApiToken,
  setAuthToken,
  clearAuthToken,
  captureAuthState,
  isAuthStateCurrent,
} from "../api/config";

export default function AuthGuard({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<
    "loading" | "auth-required" | "unavailable" | "ok"
  >("loading");

  useEffect(() => {
    let cancelled = false;
    let snapshot: ReturnType<typeof captureAuthState> | undefined;
    const current = () =>
      !cancelled && snapshot !== undefined && isAuthStateCurrent(snapshot);
    const controller = new AbortController();
    (async () => {
      try {
        snapshot = captureAuthState();
        const ssoResponse = await fetch(getApiUrl("/portal/sso/status"), {
          signal: controller.signal,
        });
        if (!current()) return;
        if (!ssoResponse.ok) {
          if (!cancelled) setStatus("unavailable");
          return;
        }
        const sso = await ssoResponse.json();
        if (!current()) return;
        if (sso.sso_required) {
          const stored = getApiToken();
          const login = async (token?: string) =>
            fetch(getApiUrl("/portal/sso/token-login"), {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(token ? { token } : {}),
              signal: controller.signal,
            });
          let response = await login(
            stored.startsWith("qp1.") ? stored : undefined,
          );
          if (!current()) return;
          if (response.status === 401 && stored.startsWith("qp1.")) {
            clearAuthToken();
            snapshot = captureAuthState();
            response = await login();
          }
          if (!current()) return;
          if (response.ok) {
            const result = await response.json();
            if (!current()) return;
            if (
              typeof result.access_token !== "string" ||
              !result.access_token.startsWith("qp1.")
            ) {
              setStatus("unavailable");
              return;
            }
            setAuthToken(result.access_token);
            setStatus("ok");
          } else if (response.status === 401) {
            const destination = new URL(
              sso.login_url ||
                `${window.location.protocol}//${window.location.hostname}:30081/login`,
              window.location.href,
            );
            if (!["http:", "https:"].includes(destination.protocol)) {
              setStatus("unavailable");
              return;
            }
            destination.searchParams.set("redirect", window.location.href);
            window.location.assign(destination.toString());
          } else {
            setStatus("unavailable");
          }
          return;
        }
        const res = await authApi.getStatus();
        if (!current()) return;
        if (!res.enabled) {
          setStatus("ok");
          return;
        }
        const token = getApiToken();
        if (!token) {
          setStatus("auth-required");
          return;
        }
        try {
          const r = await fetch(getApiUrl("/auth/verify"), {
            headers: { Authorization: `Bearer ${token}` },
            signal: controller.signal,
          });
          if (!current()) return;
          if (r.ok) {
            setStatus("ok");
          } else {
            clearAuthToken();
            setStatus("auth-required");
          }
        } catch {
          if (current()) {
            clearAuthToken();
            setStatus("auth-required");
          }
        }
      } catch {
        if (!cancelled && (!snapshot || current())) setStatus("unavailable");
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);

  useEffect(() => {
    if (status !== "ok") return;
    let stopped = false;
    let busy = false;
    let controller: AbortController | undefined;
    const timer = window.setInterval(async () => {
      const snapshot = captureAuthState();
      const token = snapshot.token;
      const current = () => !stopped && isAuthStateCurrent(snapshot);
      if (!token.startsWith("qp1.") || busy || stopped) return;
      busy = true;
      controller = new AbortController();
      try {
        const response = await fetch(getApiUrl("/portal/sso/token-login"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
          signal: controller.signal,
        });
        if (!current()) return;
        if (response.ok) {
          const result = await response.json();
          if (!current()) return;
          if (
            typeof result.access_token === "string" &&
            result.access_token.startsWith("qp1.")
          ) {
            setAuthToken(result.access_token);
          } else {
            console.error("SSO renewal returned an invalid response");
          }
        } else if (response.status === 401) {
          clearAuthToken();
          window.location.reload();
        } else {
          console.error("SSO renewal unavailable:", response.status);
        }
      } catch {
        if (current()) console.error("SSO renewal failed");
      } finally {
        busy = false;
      }
    }, 60_000);
    return () => {
      stopped = true;
      controller?.abort();
      window.clearInterval(timer);
    };
  }, [status]);

  if (status === "loading") return null;
  if (status === "unavailable")
    return (
      <div role="alert">Authentication service unavailable. Please reload.</div>
    );
  if (status === "auth-required")
    return (
      <Navigate
        to={`/login?redirect=${encodeURIComponent(window.location.pathname)}`}
        replace
      />
    );
  return <>{children}</>;
}
