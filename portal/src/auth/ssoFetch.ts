type Fetch = typeof globalThis.fetch;

const PUBLIC_SSO_PATHS = new Set([
  "GET /sso/status",
  "POST /sso/token-login",
  "POST /sso/exchange",
  "POST /sso/clear-login-cookie",
]);

export function createSsoFetch(
  fetchImpl: Fetch,
  pageUrl: string,
  apiBases: string[],
  getToken: () => string | undefined,
  onUnauthorized: () => void,
): Fetch {
  const bases = apiBases
    .map((base) => new URL(base, pageUrl))
    .sort((a, b) => b.pathname.length - a.pathname.length);
  return async (input, init) => {
    const url = new URL(
      input instanceof Request ? input.url : String(input),
      pageUrl,
    );
    const base = bases.find((candidate) => {
      const path = candidate.pathname.replace(/\/$/, "");
      return url.origin === candidate.origin &&
        (url.pathname === path || url.pathname.startsWith(`${path}/`));
    });
    if (!base) return fetchImpl(input, init);

    const token = getToken();
    const headers = new Headers(
      init?.headers ?? (input instanceof Request ? input.headers : undefined),
    );
    if (token?.startsWith("qp1.")) {
      headers.delete("X-Inoe-Token");
      headers.set("X-QwenPaw-Access-Token", token);
    } else if (token) {
      headers.delete("X-QwenPaw-Access-Token");
      headers.set("X-Inoe-Token", token);
    }
    const response = await fetchImpl(input, { ...init, headers });
    const method = (init?.method ??
      (input instanceof Request ? input.method : "GET")).toUpperCase();
    const path = url.pathname.slice(base.pathname.replace(/\/$/, "").length);
    if (
      response.status === 401 &&
      !PUBLIC_SSO_PATHS.has(`${method} ${path.replace(/\/$/, "")}`)
    ) {
      onUnauthorized();
    }
    return response;
  };
}
