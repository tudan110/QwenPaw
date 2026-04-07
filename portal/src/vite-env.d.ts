/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_COPAW_API_BASE_URL?: string;
  readonly VITE_COPAW_FALLBACK_AGENT_ID?: string;
  readonly VITE_COPAW_PROXY_TARGET?: string;
  readonly VITE_PORTAL_APP_TITLE?: string;
  readonly VITE_PORTAL_API_BASE_URL?: string;
  readonly VITE_PORTAL_PROXY_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface Window {
  __PORTAL_RUNTIME_CONFIG__?: {
    appTitle?: string;
  };
}
