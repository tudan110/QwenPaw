import { createGlobalStyle } from "antd-style";
import {
  ConfigProvider,
  bailianDarkTheme,
  bailianTheme,
} from "@agentscope-ai/design";
import { App as AntdApp } from "antd";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import jaJP from "antd/locale/ja_JP";
import ruRU from "antd/locale/ru_RU";
import idID from "antd/locale/id_ID";
import type { Locale } from "antd/es/locale";
import { theme as antdTheme } from "antd";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import "dayjs/locale/zh-cn";
import "dayjs/locale/ja";
import "dayjs/locale/ru";
import "dayjs/locale/id";
dayjs.extend(relativeTime);
import MainLayout from "./layouts/MainLayout";
import { ThemeProvider, useTheme } from "./contexts/ThemeContext";
import { PluginProvider, usePlugins } from "./plugins/PluginContext";
import { ApprovalProvider } from "./contexts/ApprovalContext";
import { DesktopUpdateProvider } from "./contexts/DesktopUpdateContext";
import { UpdateTakeoverGate } from "./components/UpdateTakeoverPage";
import { Suspense } from "react";
import { lazyImportWithRetry } from "./utils/lazyWithRetry";

const LoginPage = lazyImportWithRetry("./pages/Login/index");
import { authApi } from "./api/modules/auth";
import { languageApi } from "./api/modules/language";
import { useUploadLimitStore } from "./stores/uploadLimitStore";
import {
  getApiUrl,
  getApiToken,
  clearAuthToken,
  setAuthToken,
} from "./api/config";
import CloseWindowPrompt from "./tauri/CloseWindowPrompt";
import "./styles/layout.css";
import "./styles/form-override.css";

const antdLocaleMap: Record<string, Locale> = {
  zh: zhCN,
  en: enUS,
  ja: jaJP,
  ru: ruRU,
  id: idID,
};

const dayjsLocaleMap: Record<string, string> = {
  zh: "zh-cn",
  en: "en",
  ja: "ja",
  ru: "ru",
  id: "id",
};

const GlobalStyle = createGlobalStyle`
* {
  margin: 0;
  box-sizing: border-box;
}
`;

function AuthGuard({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<
    "loading" | "auth-required" | "unavailable" | "ok"
  >("loading");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const ssoResponse = await fetch(getApiUrl("/portal/sso/status"));
        if (!ssoResponse.ok) {
          if (!cancelled) setStatus("unavailable");
          return;
        }
        const sso = await ssoResponse.json();
        if (sso.sso_required) {
          const stored = getApiToken();
          const login = async (token?: string) =>
            fetch(getApiUrl("/portal/sso/token-login"), {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(token ? { token } : {}),
            });
          let response = await login(
            stored.startsWith("qp1.") ? stored : undefined,
          );
          if (response.status === 401 && stored.startsWith("qp1.")) {
            clearAuthToken();
            response = await login();
          }
          if (cancelled) return;
          if (response.ok) {
            const result = await response.json();
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
        if (cancelled) return;
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
          });
          if (cancelled) return;
          if (r.ok) {
            setStatus("ok");
          } else {
            clearAuthToken();
            setStatus("auth-required");
          }
        } catch {
          if (!cancelled) {
            clearAuthToken();
            setStatus("auth-required");
          }
        }
      } catch {
        if (!cancelled) setStatus("unavailable");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (status !== "ok") return;
    let stopped = false;
    let busy = false;
    const timer = window.setInterval(async () => {
      const token = getApiToken();
      if (!token.startsWith("qp1.") || busy) return;
      busy = true;
      try {
        const response = await fetch(getApiUrl("/portal/sso/token-login"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        });
        if (stopped || getApiToken() !== token) return;
        if (response.ok) {
          const result = await response.json();
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
      } catch (error) {
        console.error("SSO renewal failed:", error);
      } finally {
        busy = false;
      }
    }, 60_000);
    return () => {
      stopped = true;
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

function getRouterBasename(pathname: string): string | undefined {
  return /^\/console(?:\/|$)/.test(pathname) ? "/console" : undefined;
}

function AppInner() {
  const basename = getRouterBasename(window.location.pathname);
  const { i18n } = useTranslation();
  const { isDark } = useTheme();
  const { loading: pluginsLoading } = usePlugins();
  const selectedTheme = isDark ? bailianDarkTheme : bailianTheme;
  const lang = i18n.resolvedLanguage || i18n.language || "en";
  const [antdLocale, setAntdLocale] = useState<Locale>(
    antdLocaleMap[lang] ?? enUS,
  );

  useEffect(() => {
    if (!localStorage.getItem("language")) {
      languageApi
        .getLanguage()
        .then(({ language }) => {
          if (language && language !== i18n.language) {
            i18n.changeLanguage(language);
            localStorage.setItem("language", language);
          }
        })
        .catch((err) =>
          console.error("Failed to fetch language preference:", err),
        );
    }
    useUploadLimitStore.getState().fetch();
  }, []);

  useEffect(() => {
    const handleLanguageChanged = (lng: string) => {
      const shortLng = lng.split("-")[0];
      setAntdLocale(antdLocaleMap[shortLng] ?? enUS);
      dayjs.locale(dayjsLocaleMap[shortLng] ?? "en");
    };

    // Set initial dayjs locale
    dayjs.locale(dayjsLocaleMap[lang.split("-")[0]] ?? "en");

    i18n.on("languageChanged", handleLanguageChanged);
    return () => {
      i18n.off("languageChanged", handleLanguageChanged);
    };
  }, [i18n]);

  // Wait for plugins to load before rendering routes that might be patched
  if (pluginsLoading) {
    return null;
  }

  return (
    <BrowserRouter basename={basename}>
      <GlobalStyle />
      <ConfigProvider
        {...selectedTheme}
        prefix="qwenpaw"
        prefixCls="qwenpaw"
        locale={antdLocale}
        theme={{
          ...(selectedTheme as any)?.theme,
          algorithm: isDark
            ? antdTheme.darkAlgorithm
            : antdTheme.defaultAlgorithm,
          token: {
            colorPrimary: "#FF7F16",
          },
        }}
      >
        <AntdApp>
          <CloseWindowPrompt />
          <DesktopUpdateProvider>
            <UpdateTakeoverGate>
              <ApprovalProvider>
                <Routes>
                  <Route
                    path="/login"
                    element={
                      <Suspense fallback={null}>
                        <LoginPage />
                      </Suspense>
                    }
                  />
                  <Route
                    path="/*"
                    element={
                      <AuthGuard>
                        <MainLayout />
                      </AuthGuard>
                    }
                  />
                </Routes>
              </ApprovalProvider>
            </UpdateTakeoverGate>
          </DesktopUpdateProvider>
        </AntdApp>
      </ConfigProvider>
    </BrowserRouter>
  );
}

function App() {
  return (
    <ThemeProvider>
      <PluginProvider>
        <AppInner />
      </PluginProvider>
    </ThemeProvider>
  );
}

export default App;
