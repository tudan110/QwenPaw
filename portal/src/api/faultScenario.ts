import type {
  FaultScenarioDiagnosisRequest,
  FaultScenarioDiagnosisResponse,
} from "../fault-scenario/shared";

const DEFAULT_REQUEST_TIMEOUT_MS = 30000;

export async function diagnoseFaultScenario(
  payload: FaultScenarioDiagnosisRequest,
  options: { signal?: AbortSignal; timeoutMs?: number } = {},
): Promise<FaultScenarioDiagnosisResponse> {
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
  const timerId = window.setTimeout(() => controller.abort(), timeoutMs);
  const abortWithParentSignal = () => controller.abort();

  options.signal?.addEventListener("abort", abortWithParentSignal);

  try {
    const response = await fetch("/portal-api/fault-scenarios/diagnose", {
      method: "POST",
      signal: controller.signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error((await response.text()) || "故障场景分析失败");
    }
    return response.json();
  } catch (error: any) {
    if (error?.name === "AbortError") {
      if (options.signal?.aborted) {
        throw error;
      }
      throw new Error("故障场景分析超时，请稍后重试");
    }
    throw error;
  } finally {
    options.signal?.removeEventListener("abort", abortWithParentSignal);
    window.clearTimeout(timerId);
  }
}
