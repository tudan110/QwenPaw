const DEFAULT_REQUEST_TIMEOUT_MS = 15000;

export async function getFaultDisposalRecoveryVisualization(
  operation: Record<string, any>,
  recovery?: Record<string, any>,
) {
  const controller = new AbortController();
  const timerId = window.setTimeout(() => controller.abort(), DEFAULT_REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch("/portal-api/fault-disposal/recovery-visualization", {
      method: "POST",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        operation,
        recovery,
      }),
    });

    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || "恢复趋势图查询失败");
    }

    return response.json();
  } catch (error: any) {
    if (error?.name === "AbortError") {
      throw new Error("恢复趋势图查询超时，请稍后重试");
    }
    throw error;
  } finally {
    window.clearTimeout(timerId);
  }
}
