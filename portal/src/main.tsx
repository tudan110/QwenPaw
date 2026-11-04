import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { setPortalUnauthorizedHandler } from "./api/portalWorkorders";
import { ensureSsoLogin, triggerSsoRelogin } from "./auth/ssoConfig";
import { createSsoFetch } from "./auth/ssoFetch";
import { getSession, isAuthenticated, syncSsoTokenCookie } from "./auth/ssoSession";
import { applyPortalDocumentTitle } from "./config/portalBranding";
import "./styles.css";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Root element #root was not found");
}

// When any portal API call returns 401 mid-session (INOE token died), clear
// the session and re-login. Self-gated on SSO being enabled.
setPortalUnauthorizedHandler(triggerSsoRelogin);

syncSsoTokenCookie();
window.fetch = createSsoFetch(
  window.fetch.bind(window),
  window.location.href,
  [
    "/api",
    "/api/portal",
    "/portal-api",
    "/copaw-api/api",
    import.meta.env.VITE_COPAW_API_BASE_URL || "/copaw-api/api",
    import.meta.env.VITE_PORTAL_API_BASE_URL ||
      window.__PORTAL_RUNTIME_CONFIG__?.portalApiBaseUrl || "/portal-api",
  ],
  () => isAuthenticated() ? getSession()?.token : undefined,
  triggerSsoRelogin,
);

// Bootstrap guard (off by default). When SSO is enabled and there's no
// session yet, it silently tries the INOE login cookie first and only
// bounces to INOE if that fails. Returns false when it redirected, in which
// case we skip rendering to avoid a flash.
void ensureSsoLogin().then((proceed) => {
  if (!proceed) {
    return;
  }
  applyPortalDocumentTitle();

  ReactDOM.createRoot(rootElement).render(
    <BrowserRouter>
      <App />
    </BrowserRouter>,
  );
});
