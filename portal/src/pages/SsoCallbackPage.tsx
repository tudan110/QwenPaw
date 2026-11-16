import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { loginSsoCallback } from "../api/sso";
import { getSsoLoginRedirectUrl } from "../auth/ssoConfig";
import { setSession } from "../auth/ssoSession";

type Phase = "exchanging" | "error";

// Only allow navigating to a same-origin relative path after login, so a
// crafted ?redirect= can't bounce the user to an external site.
function safeRedirectTarget(raw: string | null): string {
  if (
    !raw ||
    !raw.startsWith("/") ||
    raw.startsWith("//") ||
    raw.includes("\\")
  ) {
    return "/";
  }
  return raw;
}

const wrapStyle: React.CSSProperties = {
  minHeight: "100vh",
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  gap: 16,
  color: "#475569",
  background: "#f8fafc",
  fontSize: 15,
};

export default function SsoCallbackPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>("exchanging");
  const [message, setMessage] = useState("正在登录...");
  // Avoid duplicate Cookie bootstrap under React StrictMode.
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) {
      return;
    }
    startedRef.current = true;

    const target = safeRedirectTarget(searchParams.get("redirect"));

    if (searchParams.has("token") || searchParams.has("code")) {
      window.history.replaceState(null, "", "/sso/callback");
    }
    const login = loginSsoCallback(searchParams);

    login
      .then((result) => {
        setSession({
          token: result.access_token,
          user: result.user,
          expiresInSeconds: result.expires_in_seconds,
        });
        navigate(target, { replace: true });
      })
      .catch((error: unknown) => {
        setPhase("error");
        setMessage(
          error instanceof Error ? error.message : "单点登录失败,请重试。",
        );
      });
  }, [navigate, searchParams]);

  if (phase === "exchanging") {
    return (
      <div style={wrapStyle}>
        <div>{message}</div>
      </div>
    );
  }

  return (
    <div style={wrapStyle}>
      <div style={{ color: "#b91c1c", maxWidth: 420, textAlign: "center" }}>
        {message}
      </div>
      <button
        type="button"
        onClick={() => {
          // After login, come back to the portal home (this page has no code).
          window.location.href = getSsoLoginRedirectUrl(
            `${window.location.origin}/`,
          );
        }}
        style={{
          padding: "8px 20px",
          borderRadius: 8,
          border: "none",
          background: "#2563eb",
          color: "#fff",
          fontSize: 14,
          cursor: "pointer",
        }}
      >
        重新登录
      </button>
    </div>
  );
}
