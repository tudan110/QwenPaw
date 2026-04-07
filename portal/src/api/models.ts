const DEFAULT_API_BASE_URL = "/copaw-api/api";

const API_BASE_URL = (import.meta.env.VITE_COPAW_API_BASE_URL || DEFAULT_API_BASE_URL).replace(
  /\/$/,
  "",
);

export interface ModelInfo {
  id: string;
  name: string;
  supports_multimodal?: boolean | null;
  supports_image?: boolean | null;
  supports_video?: boolean | null;
  generate_kwargs?: Record<string, unknown>;
}

export interface ProviderInfo {
  id: string;
  name: string;
  api_key_prefix?: string;
  chat_model?: string;
  models?: ModelInfo[];
  extra_models?: ModelInfo[];
  is_custom?: boolean;
  is_local?: boolean;
  support_model_discovery?: boolean;
  support_connection_check?: boolean;
  freeze_url?: boolean;
  require_api_key?: boolean;
  api_key?: string;
  base_url?: string;
  generate_kwargs?: Record<string, unknown>;
}

export interface ModelSlotConfig {
  provider_id: string;
  model: string;
}

export interface ActiveModelsInfo {
  active_llm?: ModelSlotConfig;
}

export type ActiveModelScope = "effective" | "global" | "agent";

export interface GetActiveModelsRequest {
  scope?: ActiveModelScope;
  agent_id?: string;
}

export interface ModelSlotRequest {
  provider_id: string;
  model: string;
  scope: Exclude<ActiveModelScope, "effective">;
  agent_id?: string;
}

export interface CreateCustomProviderRequest {
  id: string;
  name: string;
  default_base_url?: string;
  api_key_prefix?: string;
  chat_model?: string;
  models?: ModelInfo[];
}

export interface ProviderConfigRequest {
  name?: string;
  api_key?: string;
  base_url?: string;
  chat_model?: string;
  generate_kwargs?: Record<string, unknown>;
}

export interface AddModelRequest {
  id: string;
  name: string;
}

export interface ModelConfigRequest {
  generate_kwargs?: Record<string, unknown>;
}

export interface TestConnectionResponse {
  success: boolean;
  message: string;
}

export interface TestProviderRequest {
  api_key?: string;
  base_url?: string;
  chat_model?: string;
  generate_kwargs?: Record<string, unknown>;
}

export interface TestModelRequest {
  model_id: string;
  api_key?: string;
  base_url?: string;
  chat_model?: string;
  generate_kwargs?: Record<string, unknown>;
}

export interface DiscoverModelsResponse {
  success: boolean;
  message: string;
  models: ModelInfo[];
  added_count: number;
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

async function requestModels<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      ...(options.method && !["GET", "HEAD"].includes(options.method.toUpperCase())
        ? { "Content-Type": "application/json" }
        : {}),
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(
      extractErrorMessage(text) || `模型服务请求失败：${response.status}`,
    );
  }

  if (response.status === 204) {
    return null as T;
  }

  return response.json();
}

function buildActiveModelQuery(params?: GetActiveModelsRequest) {
  if (!params?.scope && !params?.agent_id) {
    return "/models/active";
  }

  const searchParams = new URLSearchParams();
  if (params.scope) {
    searchParams.set("scope", params.scope);
  }
  if (params.agent_id) {
    searchParams.set("agent_id", params.agent_id);
  }

  return `/models/active?${searchParams.toString()}`;
}

export const modelsApi = {
  listProviders: () => requestModels<ProviderInfo[]>("/models"),

  getActiveModels: (params?: GetActiveModelsRequest) =>
    requestModels<ActiveModelsInfo>(buildActiveModelQuery(params)),

  setActiveLlm: (body: ModelSlotRequest) =>
    requestModels<ActiveModelsInfo>("/models/active", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  createCustomProvider: (body: CreateCustomProviderRequest) =>
    requestModels<ProviderInfo>("/models/custom-providers", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  deleteCustomProvider: (providerId: string) =>
    requestModels<ProviderInfo[]>(
      `/models/custom-providers/${encodeURIComponent(providerId)}`,
      { method: "DELETE" },
    ),

  configureProvider: (providerId: string, body: ProviderConfigRequest) =>
    requestModels<ProviderInfo>(`/models/${encodeURIComponent(providerId)}/config`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  addModel: (providerId: string, body: AddModelRequest) =>
    requestModels<ProviderInfo>(`/models/${encodeURIComponent(providerId)}/models`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  configureModel: (providerId: string, modelId: string, body: ModelConfigRequest) =>
    requestModels<ProviderInfo>(
      `/models/${encodeURIComponent(providerId)}/models/${encodeURIComponent(modelId)}/config`,
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    ),

  removeModel: (providerId: string, modelId: string) =>
    requestModels<ProviderInfo>(
      `/models/${encodeURIComponent(providerId)}/models/${encodeURIComponent(modelId)}`,
      { method: "DELETE" },
    ),

  testProviderConnection: (providerId: string, body?: TestProviderRequest) =>
    requestModels<TestConnectionResponse>(`/models/${encodeURIComponent(providerId)}/test`, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    }),

  testModelConnection: (providerId: string, body: TestModelRequest) =>
    requestModels<TestConnectionResponse>(
      `/models/${encodeURIComponent(providerId)}/models/test`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    ),

  discoverModels: (providerId: string, body?: TestProviderRequest) =>
    requestModels<DiscoverModelsResponse>(
      `/models/${encodeURIComponent(providerId)}/discover`,
      {
        method: "POST",
        body: body ? JSON.stringify(body) : undefined,
      },
    ),
};
