const DEFAULT_API_BASE_URL = "/copaw-api/api";

const API_BASE_URL = (import.meta.env.VITE_COPAW_API_BASE_URL || DEFAULT_API_BASE_URL).replace(
  /\/$/,
  "",
);

interface SkillsRequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

export interface PoolSkillInfo {
  name: string;
  description: string;
  emoji: string;
  version_text: string;
  content: string;
  references: Record<string, unknown>;
  scripts: Record<string, unknown>;
  source: string;
  protected: boolean;
  commit_text: string;
  sync_status: string;
  latest_version_text: string;
  tags: string[];
  config: Record<string, unknown>;
  last_updated: string;
}

export interface WorkspaceSkillInfo {
  name: string;
  description: string;
  emoji: string;
  version_text: string;
  content: string;
  references: Record<string, unknown>;
  scripts: Record<string, unknown>;
  source: string;
  tags: string[];
  config: Record<string, unknown>;
  last_updated: string;
  enabled: boolean;
  channels: string[];
}

export interface WorkspaceSkillSummary {
  agent_id: string;
  agent_name: string;
  workspace_dir: string;
  skills: WorkspaceSkillInfo[];
}

export interface CreatePoolSkillRequest {
  name: string;
  content: string;
  config?: Record<string, unknown>;
}

export interface SavePoolSkillRequest {
  name: string;
  content: string;
  sourceName?: string;
  config?: Record<string, unknown>;
}

export interface SavePoolSkillResult {
  success: boolean;
  mode?: "edit" | "rename";
  name?: string;
  reason?: string;
  suggested_name?: string;
}

function extractErrorMessage(text: string) {
  if (!text) {
    return "";
  }

  try {
    const payload = JSON.parse(text) as {
      detail?: unknown;
      message?: unknown;
      error?: unknown;
    };

    if (typeof payload.detail === "string" && payload.detail) {
      return payload.detail;
    }

    if (payload.detail && typeof payload.detail === "object") {
      const detail = payload.detail as {
        reason?: unknown;
        suggested_name?: unknown;
      };
      if (typeof detail.suggested_name === "string" && detail.suggested_name) {
        return `技能名冲突，建议改用：${detail.suggested_name}`;
      }
      if (typeof detail.reason === "string" && detail.reason) {
        return `技能保存失败：${detail.reason}`;
      }
      return JSON.stringify(detail);
    }

    if (typeof payload.message === "string" && payload.message) {
      return payload.message;
    }

    if (typeof payload.error === "string" && payload.error) {
      return payload.error;
    }
  } catch {
    return text;
  }

  return text;
}

async function requestSkills<T>(
  path: string,
  { method = "GET", body, signal }: SkillsRequestOptions = {},
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    signal,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (response.ok) {
    if (response.status === 204) {
      return null as T;
    }
    return response.json() as Promise<T>;
  }

  const responseText = await response.text().catch(() => "");
  const errorMessage = extractErrorMessage(responseText);
  throw new Error(errorMessage || `技能池请求失败：${response.status}`);
}

export const skillsApi = {
  listPoolSkills: (signal?: AbortSignal) =>
    requestSkills<PoolSkillInfo[]>("/skills/pool", { signal }),

  refreshPoolSkills: () =>
    requestSkills<PoolSkillInfo[]>("/skills/pool/refresh", { method: "POST" }),

  listWorkspaceSkills: (signal?: AbortSignal) =>
    requestSkills<WorkspaceSkillSummary[]>("/skills/workspaces", { signal }),

  createPoolSkill: (payload: CreatePoolSkillRequest) =>
    requestSkills<{ created: boolean; name: string }>("/skills/pool/create", {
      method: "POST",
      body: payload,
    }),

  savePoolSkill: (payload: SavePoolSkillRequest) =>
    requestSkills<SavePoolSkillResult>("/skills/pool/save", {
      method: "PUT",
      body: {
        name: payload.name,
        content: payload.content,
        source_name: payload.sourceName,
        config: payload.config || {},
      },
    }),

  updatePoolSkillTags: (skillName: string, tags: string[]) => {
    const params = new URLSearchParams();
    if (tags.length) {
      tags.forEach((tag) => params.append("tags", tag));
    } else {
      params.append("tags", "");
    }
    return requestSkills<{ updated: boolean; tags: string[] }>(
      `/skills/pool/${encodeURIComponent(skillName)}/tags?${params.toString()}`,
      { method: "PUT" },
    );
  },

  deletePoolSkill: (skillName: string) =>
    requestSkills<{ deleted: boolean }>(`/skills/pool/${encodeURIComponent(skillName)}`, {
      method: "DELETE",
    }),
};
