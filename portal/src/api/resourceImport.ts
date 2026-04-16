import type {
  ResourceImportMetadata,
  ResourceImportPreviewJob,
  ResourceImportPreview,
  ResourceImportResult,
  ResourceImportStartPayload,
} from "../types/resourceImport";

const DEFAULT_PORTAL_API_BASE_URL = "/portal-api";
const DEFAULT_REQUEST_TIMEOUT_MS = 30000;
const DEFAULT_FALLBACK_AGENT_ID = "default";

const PORTAL_API_BASE_URL = (
  import.meta.env.VITE_PORTAL_API_BASE_URL || DEFAULT_PORTAL_API_BASE_URL
).replace(/\/$/, "");

function getAgentCandidates(agentId?: string) {
  const fallbackAgentId =
    import.meta.env.VITE_COPAW_FALLBACK_AGENT_ID || DEFAULT_FALLBACK_AGENT_ID;
  return [...new Set([agentId, fallbackAgentId].filter(Boolean))];
}

function isMissingAgentResponse(status: number, errorText?: string) {
  return status === 404 && /Agent\s+['"].+['"]\s+not\s+found/i.test(errorText || "");
}

async function requestPortalApi<T = unknown>(
  path: string,
  init: RequestInit = {},
  timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
  agentId?: string,
): Promise<T> {
  const agentCandidates = getAgentCandidates(agentId);
  let lastErrorText = "";
  let lastStatus = 0;

  for (const candidateAgentId of agentCandidates) {
    const controller = new AbortController();
    const timerId = window.setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(`${PORTAL_API_BASE_URL}${path}`, {
        ...init,
        signal: controller.signal,
        headers: {
          ...(init.headers || {}),
          ...(candidateAgentId ? { "X-Agent-Id": candidateAgentId } : {}),
        },
      });

      if (response.ok) {
        return response.json();
      }

      lastStatus = response.status;
      lastErrorText = await response.text().catch(() => "");
      if (!isMissingAgentResponse(response.status, lastErrorText)) {
        throw new Error(lastErrorText || "资源导入请求失败");
      }
    } catch (error: any) {
      if (error?.name === "AbortError") {
        throw new Error("请求超时，请稍后重试");
      }
      throw error;
    } finally {
      window.clearTimeout(timerId);
    }
  }

  throw new Error(lastErrorText || `资源导入请求失败：${lastStatus}`);
}

export function getResourceImportMetadata(agentId?: string) {
  return requestPortalApi<ResourceImportMetadata>("/resource-import/metadata", {}, undefined, agentId);
}

export function getResourceImportStart(agentId?: string) {
  return requestPortalApi<ResourceImportStartPayload>("/resource-import/start", {}, undefined, agentId);
}

export function startResourceImportPreview(files: File[], agentId?: string) {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file, file.name));
  return requestPortalApi<ResourceImportPreviewJob>(
    "/resource-import/preview",
    {
      method: "POST",
      body: formData,
    },
    30000,
    agentId,
  );
}

export function getResourceImportPreviewJob(jobId: string, agentId?: string) {
  return requestPortalApi<ResourceImportPreviewJob>(
    `/resource-import/preview/${encodeURIComponent(jobId)}`,
    {},
    30000,
    agentId,
  );
}

export async function previewResourceImport(
  files: File[],
  agentId?: string,
  options?: {
    onProgress?: (job: ResourceImportPreviewJob) => void;
    pollIntervalMs?: number;
    maxWaitMs?: number;
  },
) {
  const pollIntervalMs = options?.pollIntervalMs ?? 1500;
  const maxWaitMs = options?.maxWaitMs ?? 15 * 60 * 1000;
  const startedAt = Date.now();
  const initialJob = await startResourceImportPreview(files, agentId);
  options?.onProgress?.(initialJob);

  let currentJob = initialJob;
  while (Date.now() - startedAt <= maxWaitMs) {
    if (currentJob.status === "completed" && currentJob.preview) {
      return currentJob.preview;
    }
    if (currentJob.status === "failed") {
      throw new Error(currentJob.error || "资源解析失败");
    }
    await new Promise((resolve) => window.setTimeout(resolve, pollIntervalMs));
    currentJob = await getResourceImportPreviewJob(initialJob.jobId, agentId);
    options?.onProgress?.(currentJob);
  }

  throw new Error("资源解析超时，请稍后重试");
}

export function submitResourceImport(payload: Record<string, unknown>, agentId?: string) {
  return requestPortalApi<ResourceImportResult>(
    "/resource-import/import",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
    120000,
    agentId,
  );
}
