import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

function buildProxyTarget(rawTarget: string | undefined, fallbackTarget: string) {
  return (rawTarget || fallbackTarget).replace(/\/$/, "");
}

function buildProxyConfig(target: string, prefix: string, rewritePrefix = "") {
  return {
    target,
    changeOrigin: true,
    rewrite: (path: string) =>
      path.replace(new RegExp(`^${prefix}`), rewritePrefix),
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const copawTarget = buildProxyTarget(
    env.VITE_COPAW_PROXY_TARGET,
    "http://127.0.0.1:8088",
  );
  const portalApiTarget = buildProxyTarget(
    env.VITE_PORTAL_PROXY_TARGET,
    "http://127.0.0.1:8088",
  );

  return {
    plugins: [react()],
    server: {
      proxy: {
        "/copaw-api": buildProxyConfig(copawTarget, "/copaw-api"),
        "/portal-api": buildProxyConfig(
          portalApiTarget,
          "/portal-api",
          "/api/portal",
        ),
      },
    },
    preview: {
      proxy: {
        "/copaw-api": buildProxyConfig(copawTarget, "/copaw-api"),
        "/portal-api": buildProxyConfig(
          portalApiTarget,
          "/portal-api",
          "/api/portal",
        ),
      },
    },
  };
});
