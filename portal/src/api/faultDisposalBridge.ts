const DEFAULT_REQUEST_TIMEOUT_MS = 30000;

async function requestFaultDisposalApi<T = unknown>(
  path: string,
  init: RequestInit = {},
  timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timerId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`/portal-api${path}`, {
      ...init,
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error((await response.text()) || "故障处置请求失败");
    }

    return response.json();
  } catch (error: any) {
    if (error?.name === "AbortError") {
      throw new Error("故障处置请求超时，请稍后重试");
    }
    throw error;
  } finally {
    window.clearTimeout(timerId);
  }
}

export async function diagnoseFaultDisposal(payload: Record<string, any>) {
  return requestFaultDisposalApi("/fault-disposal/diagnose", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function executeFaultDisposal(payload: Record<string, any>) {
  return requestFaultDisposalApi("/fault-disposal/execute", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function getFaultDisposalHistory(sessionId: string) {
  return requestFaultDisposalApi(
    `/fault-disposal/history/${encodeURIComponent(sessionId)}`,
  );
}
