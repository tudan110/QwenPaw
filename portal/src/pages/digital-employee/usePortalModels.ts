import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  modelsApi,
  type ModelInfo,
  type ActiveModelsInfo,
  type ProviderInfo,
} from "../../api/models";

const DEFAULT_MODEL_AGENT_ID = "default";
export const DEFAULT_PROVIDER_SLOT_ID = "default-provider-slot";
const DEFAULT_PROVIDER_SLOT_NAME = "test1";
const DEFAULT_PROVIDER_MODELS: ModelInfo[] = [
  { id: "qiming1.0", name: "启明1.0" },
  { id: "deepseek3.2", name: "deepseek3.2" },
  { id: "qwen3.5", name: "qwen3.5" },
];

export type ModelNoticeTone = "success" | "error" | "info";

export interface ModelNoticeState {
  tone: ModelNoticeTone;
  text: string;
}

export interface EligibleProvider {
  id: string;
  name: string;
  isCustom: boolean;
  description: string;
  models: Array<{ id: string; name: string }>;
}

export interface DisplayProvider {
  id: string;
  name: string;
  isCustom: boolean;
  isLocal: boolean;
  baseUrl: string;
  apiKeyMasked: string;
  apiKeyConfigured: boolean;
  description: string;
  requireApiKey: boolean;
  supportModelDiscovery: boolean;
  configured: boolean;
  generateKwargs: Record<string, unknown>;
  models: Array<{
    id: string;
    name: string;
    generateKwargs: Record<string, unknown>;
  }>;
}

export interface ConnectModelPayload {
  providerId?: string;
  providerName: string;
  baseUrl: string;
  apiKey: string;
  modelId: string;
  modelName?: string;
  protocol?: string;
  setActive?: boolean;
  generateConfigText?: string;
}

export interface BuiltinApiKeyApplyPayload {
  quotaServiceName: string;
  appIds: string[];
  expirePreset: "30d" | "90d" | "180d" | "forever";
}

export interface BuiltinApiKeyApplyResult {
  apiKey: string;
  expireAt: string;
  serviceName: string;
  appNames: string[];
}

function flattenModels(provider?: ProviderInfo) {
  const merged = [...(provider?.models || []), ...(provider?.extra_models || [])];
  const deduped: ModelInfo[] = [];
  const seen = new Set<string>();
  for (const model of merged) {
    const id = String(model?.id || "").trim();
    if (!id || seen.has(id)) {
      continue;
    }
    seen.add(id);
    deduped.push(model);
  }
  return deduped;
}

function buildDisplayProviders(providerList: ProviderInfo[]) {
  const source = providerList.map((provider, index) => ({
    ...provider,
    __order: index,
  }));

  const slotExisting = source.find((provider) => provider.id === DEFAULT_PROVIDER_SLOT_ID);
  const slotModels = [
    ...DEFAULT_PROVIDER_MODELS,
    ...flattenModels(slotExisting),
  ].reduce<ModelInfo[]>((acc, model) => {
    if (!acc.some((item) => item.id === model.id)) {
      acc.push(model);
    }
    return acc;
  }, []);

  const defaultProvider: ProviderInfo & { __order: number } = {
    ...(slotExisting || {}),
    id: DEFAULT_PROVIDER_SLOT_ID,
    name: slotExisting?.name || DEFAULT_PROVIDER_SLOT_NAME,
    is_custom: true,
    is_local: false,
    require_api_key: true,
    base_url: slotExisting?.base_url || "",
    chat_model: slotExisting?.chat_model || "OpenAIChatModel",
    support_model_discovery: false,
    models: slotModels,
    extra_models: [],
    __order: -1,
  };

  return source
    .filter((provider) => provider.id !== DEFAULT_PROVIDER_SLOT_ID)
    .concat(defaultProvider)
    .sort((left, right) => {
      if (
        left.id === DEFAULT_PROVIDER_SLOT_ID
        && right.id !== DEFAULT_PROVIDER_SLOT_ID
      ) {
        return -1;
      }
      if (
        right.id === DEFAULT_PROVIDER_SLOT_ID
        && left.id !== DEFAULT_PROVIDER_SLOT_ID
      ) {
        return 1;
      }
      return left.__order - right.__order;
    })
    .map(({ __order, ...provider }) => provider as ProviderInfo);
}

function isProviderConfigured(provider: ProviderInfo) {
  const hasModels = flattenModels(provider).length > 0;
  if (!hasModels) {
    return false;
  }
  if (provider.require_api_key === false) {
    return Boolean(provider.base_url);
  }
  if (provider.is_custom) {
    return Boolean(provider.base_url);
  }
  if (provider.require_api_key ?? true) {
    return Boolean(provider.api_key);
  }
  return true;
}

function slugifyProviderId(value: string) {
  const normalized = value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");

  const candidate = normalized || "custom-model-provider";
  const withPrefix = /^[a-z]/.test(candidate) ? candidate : `m-${candidate}`;
  return withPrefix.slice(0, 64);
}

function buildProviderDescription(provider: ProviderInfo) {
  if (provider.is_custom) {
    return provider.base_url || "自定义协议接入";
  }
  if (provider.base_url) {
    return provider.base_url;
  }
  if (provider.is_local) {
    return "本地模型服务";
  }
  return "系统内置模型源";
}

function generateBuiltinApiKey() {
  const charset = "abcdefghijklmnopqrstuvwxyz0123456789";
  let value = "";
  for (let i = 0; i < 32; i += 1) {
    value += charset[Math.floor(Math.random() * charset.length)];
  }
  return value;
}

function parseGenerateConfig(text?: string) {
  const trimmed = text?.trim() || "";
  if (!trimmed) {
    return { ok: true as const, value: {} as Record<string, unknown> };
  }

  try {
    const parsed = JSON.parse(trimmed);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false as const, error: "高级配置必须是 JSON 对象" };
    }
    return { ok: true as const, value: parsed as Record<string, unknown> };
  } catch {
    return { ok: false as const, error: "高级配置不是合法的 JSON" };
  }
}

export function usePortalModels({
  agentId,
  enabled = true,
}: {
  agentId?: string | null;
  enabled?: boolean;
}) {
  const resolvedAgentId = agentId || DEFAULT_MODEL_AGENT_ID;
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [activeModels, setActiveModels] = useState<ActiveModelsInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<ModelNoticeState | null>(null);

  const providersRef = useRef<ProviderInfo[]>([]);
  const noticeTimerRef = useRef<number>(0);

  const clearNotice = useCallback(() => {
    if (noticeTimerRef.current) {
      window.clearTimeout(noticeTimerRef.current);
      noticeTimerRef.current = 0;
    }
    setNotice(null);
  }, []);

  const pushNotice = useCallback(
    (tone: ModelNoticeTone, text: string, timeout = 4200) => {
      clearNotice();
      setNotice({ tone, text });
      if (timeout > 0) {
        noticeTimerRef.current = window.setTimeout(() => {
          noticeTimerRef.current = 0;
          setNotice(null);
        }, timeout) as unknown as number;
      }
    },
    [clearNotice],
  );

  useEffect(
    () => () => {
      if (noticeTimerRef.current) {
        window.clearTimeout(noticeTimerRef.current);
      }
    },
    [],
  );

  const fetchModelState = useCallback(async () => {
    if (!enabled) {
      return;
    }

    setLoading(true);
    try {
      const [providerList, active] = await Promise.all([
        modelsApi.listProviders(),
        modelsApi.getActiveModels({
          scope: "effective",
          agent_id: resolvedAgentId,
        }),
      ]);

      const nextProviders = Array.isArray(providerList) ? providerList : [];
      setProviders(buildDisplayProviders(nextProviders));
      providersRef.current = nextProviders;
      setActiveModels(active || null);
    } catch (error: any) {
      pushNotice("error", error?.message || "模型配置加载失败");
    } finally {
      setLoading(false);
    }
  }, [enabled, pushNotice, resolvedAgentId]);

  useEffect(() => {
    void fetchModelState();
  }, [fetchModelState]);

  const eligibleProviders = useMemo<EligibleProvider[]>(
    () =>
      providers
        .filter((provider) => isProviderConfigured(provider))
        .map((provider) => ({
          id: provider.id,
          name: provider.name,
          isCustom: Boolean(provider.is_custom),
          description: buildProviderDescription(provider),
          models: flattenModels(provider).map((model) => ({
            id: model.id,
            name: model.name || model.id,
          })),
        }))
        .filter((provider) => provider.models.length > 0),
    [providers],
  );

  const displayProviders = useMemo<DisplayProvider[]>(
    () =>
      providers.map((provider) => ({
        id: provider.id,
        name: provider.name,
        isCustom: Boolean(provider.is_custom),
        isLocal: Boolean(provider.is_local),
        baseUrl: provider.base_url || "",
        apiKeyMasked: provider.api_key || "",
        apiKeyConfigured: Boolean(provider.api_key),
        description: buildProviderDescription(provider),
        requireApiKey: provider.require_api_key ?? true,
        supportModelDiscovery: Boolean(provider.support_model_discovery),
        configured: isProviderConfigured(provider),
        generateKwargs: provider.generate_kwargs || {},
        models: flattenModels(provider).map((model) => ({
          id: model.id,
          name: model.name || model.id,
          generateKwargs: model.generate_kwargs || {},
        })),
      })),
    [providers],
  );

  const activeProviderId = activeModels?.active_llm?.provider_id || "";
  const activeModelId = activeModels?.active_llm?.model || "";

  const activeModelLabel = useMemo(() => {
    if (!activeProviderId || !activeModelId) {
      return "选择模型";
    }

    const provider = eligibleProviders.find((item) => item.id === activeProviderId);
    const model = provider?.models.find((item) => item.id === activeModelId);
    return model?.name || activeModelId;
  }, [activeModelId, activeProviderId, eligibleProviders]);

  const activeProviderName = useMemo(() => {
    const provider = providers.find((item) => item.id === activeProviderId);
    return provider?.name || activeProviderId || "默认模型源";
  }, [activeProviderId, providers]);

  const handleSelectModel = useCallback(async (
    providerId: string,
    modelId: string,
  ) => {
    if (!providerId || !modelId || switching) {
      return false;
    }

    if (providerId === activeProviderId && modelId === activeModelId) {
      return true;
    }

    setSwitching(true);
    try {
      const nextActive = await modelsApi.setActiveLlm({
        provider_id: providerId,
        model: modelId,
        scope: "agent",
        agent_id: resolvedAgentId,
      });

      setActiveModels(nextActive || {
        active_llm: {
          provider_id: providerId,
          model: modelId,
        },
      });
      window.dispatchEvent(new CustomEvent("model-switched"));
      pushNotice("success", `当前会话已切换到 ${modelId}`);
      return true;
    } catch (error: any) {
      pushNotice("error", error?.message || "模型切换失败");
      return false;
    } finally {
      setSwitching(false);
    }
  }, [
    activeModelId,
    activeProviderId,
    pushNotice,
    resolvedAgentId,
    switching,
  ]);

  const handleConnectModel = useCallback(async (payload: ConnectModelPayload) => {
    const providerId = slugifyProviderId(
      payload.providerId?.trim() || payload.providerName || payload.modelId,
    );
    const existingProvider = providersRef.current.find(
      (provider) => provider.id === providerId,
    );
    const providerName = payload.providerName.trim() || existingProvider?.name || "";
    const baseUrl = payload.baseUrl.trim() || existingProvider?.base_url || "";
    const apiKey = payload.apiKey.trim();
    const modelId = payload.modelId.trim();
    const modelName = (payload.modelName || payload.modelId).trim();
    const protocol =
      payload.protocol || existingProvider?.chat_model || "OpenAIChatModel";
    const existingModels = flattenModels(existingProvider);
    const requiresApiKey = existingProvider?.require_api_key ?? true;
    const hasExistingApiKey = Boolean(existingProvider?.api_key);
    const parsedGenerateConfig = parseGenerateConfig(payload.generateConfigText);
    const isDefaultSlot = providerId === DEFAULT_PROVIDER_SLOT_ID;
    const defaultModelId = DEFAULT_PROVIDER_MODELS[0]?.id || "";
    const defaultModelName = DEFAULT_PROVIDER_MODELS[0]?.name || defaultModelId;
    const isNameOnlySave =
      isDefaultSlot
      && !baseUrl
      && !apiKey
      && !modelId
      && existingModels.length === 0;

    if (!providerName) {
      pushNotice("error", "请填写模型提供商名称");
      return false;
    }

    if (!parsedGenerateConfig.ok) {
      pushNotice("error", parsedGenerateConfig.error);
      return false;
    }

    if (!isNameOnlySave && !baseUrl && !existingProvider?.is_local) {
      pushNotice("error", "请填写模型服务地址");
      return false;
    }

    if (!isNameOnlySave && requiresApiKey && !apiKey && !hasExistingApiKey) {
      pushNotice("error", "请填写 API Key");
      return false;
    }

    if (
      !isNameOnlySave
      && !modelId
      && existingModels.length === 0
      && !isDefaultSlot
    ) {
      pushNotice("error", "请填写 MODEL ID");
      return false;
    }

    setSubmitting(true);
    try {
      if (!existingProvider) {
        await modelsApi.createCustomProvider({
          id: providerId,
          name: providerName,
          default_base_url: baseUrl,
          chat_model: protocol,
          models: isDefaultSlot && !isNameOnlySave ? DEFAULT_PROVIDER_MODELS : undefined,
        });
      }

      let configuredProvider = await modelsApi.configureProvider(providerId, {
        name: providerName || undefined,
        api_key: apiKey || undefined,
        base_url: baseUrl || undefined,
        chat_model: protocol,
        generate_kwargs: parsedGenerateConfig.value,
      });

      const effectiveModelId = modelId || (isNameOnlySave ? "" : defaultModelId);
      const effectiveModelName = modelName || (
        effectiveModelId === defaultModelId ? defaultModelName : effectiveModelId
      );
      const modelExists = effectiveModelId
        ? flattenModels(configuredProvider).some((model) => model.id === effectiveModelId)
        : true;

      if (effectiveModelId && !modelExists) {
        configuredProvider = await modelsApi.addModel(providerId, {
          id: effectiveModelId,
          name: effectiveModelName || effectiveModelId,
        });
      }

      await fetchModelState();

      const targetModelId =
        effectiveModelId || flattenModels(configuredProvider)[0]?.id || "";

      if (payload.setActive !== false) {
        if (targetModelId && !isNameOnlySave) {
          await handleSelectModel(providerId, targetModelId);
        } else {
          pushNotice("success", `${providerName} 已保存`);
        }
      } else {
        pushNotice(
          "success",
          targetModelId
            ? `模型 ${effectiveModelName || targetModelId} 已接入`
            : `${providerName} 已保存`,
        );
      }

      return true;
    } catch (error: any) {
      pushNotice("error", error?.message || "模型接入失败");
      return false;
    } finally {
      setSubmitting(false);
    }
  }, [fetchModelState, handleSelectModel, pushNotice]);

  const handleDeleteProvider = useCallback(async (providerId: string) => {
    if (!providerId) {
      return false;
    }

    setSubmitting(true);
    try {
      await modelsApi.deleteCustomProvider(providerId);
      await fetchModelState();
      pushNotice("success", `已删除提供商 ${providerId}`);
      return true;
    } catch (error: any) {
      pushNotice("error", error?.message || "删除提供商失败");
      return false;
    } finally {
      setSubmitting(false);
    }
  }, [fetchModelState, pushNotice]);

  const handleApplyBuiltinApiKey = useCallback(async (
    payload: BuiltinApiKeyApplyPayload,
  ) => {
    if (!payload.quotaServiceName.trim()) {
      pushNotice("error", "请填写名称");
      return null;
    }
    if (!payload.appIds.length) {
      pushNotice("error", "请至少选择一个模型应用");
      return null;
    }

    setSubmitting(true);
    try {
      const now = Date.now();
      const expireAtMap: Record<BuiltinApiKeyApplyPayload["expirePreset"], string> = {
        "30d": new Date(now + 30 * 24 * 60 * 60 * 1000).toISOString(),
        "90d": new Date(now + 90 * 24 * 60 * 60 * 1000).toISOString(),
        "180d": new Date(now + 180 * 24 * 60 * 60 * 1000).toISOString(),
        forever: "2099-12-31T23:59:59Z",
      };
      const modelNameMap: Record<string, string> = {
        "qiming1.0": "启明1.0",
        "deepseek3.2": "DeepSeek3.2",
        "qwen3.5": "Qwen3.5",
      };

      pushNotice("success", "API Key 已生成");
      return {
        apiKey: generateBuiltinApiKey(),
        expireAt: expireAtMap[payload.expirePreset],
        serviceName: payload.quotaServiceName.trim(),
        appNames: payload.appIds.map((id) => modelNameMap[id] || id),
      } satisfies BuiltinApiKeyApplyResult;
    } catch (error: any) {
      pushNotice("error", error?.message || "获取 API Key 失败");
      return null;
    } finally {
      setSubmitting(false);
    }
  }, [pushNotice]);

  const handleRemoveModel = useCallback(async (
    providerId: string,
    modelId: string,
  ) => {
    if (!providerId || !modelId) {
      return false;
    }

    setSubmitting(true);
    try {
      await modelsApi.removeModel(providerId, modelId);
      await fetchModelState();
      pushNotice("success", `已移除模型 ${modelId}`);
      return true;
    } catch (error: any) {
      pushNotice("error", error?.message || "移除模型失败");
      return false;
    } finally {
      setSubmitting(false);
    }
  }, [fetchModelState, pushNotice]);

  const handleTestProvider = useCallback(async (
    providerId: string,
    payload?: {
      apiKey?: string;
      baseUrl?: string;
      protocol?: string;
      modelId?: string;
      generateConfigText?: string;
    },
  ) => {
    if (!providerId) {
      return false;
    }

    const parsedGenerateConfig = parseGenerateConfig(payload?.generateConfigText);
    if (!parsedGenerateConfig.ok) {
      pushNotice("error", parsedGenerateConfig.error);
      return false;
    }

    setSwitching(true);
    try {
      const providerResponse = await modelsApi.testProviderConnection(providerId, {
        api_key: payload?.apiKey || undefined,
        base_url: payload?.baseUrl || undefined,
        chat_model: payload?.protocol || undefined,
        generate_kwargs: parsedGenerateConfig.value,
      });

      if (!providerResponse?.success) {
        pushNotice("error", providerResponse?.message || "连接测试失败");
        return false;
      }

      const modelId = payload?.modelId?.trim();
      if (modelId) {
        const modelResponse = await modelsApi.testModelConnection(providerId, {
          model_id: modelId,
          api_key: payload?.apiKey || undefined,
          base_url: payload?.baseUrl || undefined,
          chat_model: payload?.protocol || undefined,
          generate_kwargs: parsedGenerateConfig.value,
        });
        pushNotice(
          modelResponse?.success ? "success" : "error",
          modelResponse?.message || "模型测试已完成",
        );
        return Boolean(modelResponse?.success);
      }

      pushNotice("success", providerResponse?.message || "连接测试已完成");
      return true;
    } catch (error: any) {
      pushNotice("error", error?.message || "连接测试失败");
      return false;
    } finally {
      setSwitching(false);
    }
  }, [pushNotice]);

  const handleTestModel = useCallback(async (providerId: string, modelId: string) => {
    if (!providerId || !modelId) {
      return false;
    }

    setSwitching(true);
    try {
      const response = await modelsApi.testModelConnection(providerId, {
        model_id: modelId,
      });
      pushNotice(
        response?.success ? "success" : "error",
        response?.message || "模型测试已完成",
      );
      return Boolean(response?.success);
    } catch (error: any) {
      pushNotice("error", error?.message || "模型测试失败");
      return false;
    } finally {
      setSwitching(false);
    }
  }, [pushNotice]);

  const handleConfigureModel = useCallback(async (
    providerId: string,
    modelId: string,
    generateConfigText: string,
  ) => {
    if (!providerId || !modelId) {
      return false;
    }

    const parsedGenerateConfig = parseGenerateConfig(generateConfigText);
    if (!parsedGenerateConfig.ok) {
      pushNotice("error", parsedGenerateConfig.error);
      return false;
    }

    setSubmitting(true);
    try {
      await modelsApi.configureModel(providerId, modelId, {
        generate_kwargs: parsedGenerateConfig.value,
      });
      await fetchModelState();
      pushNotice("success", `模型 ${modelId} 的高级配置已保存`);
      return true;
    } catch (error: any) {
      pushNotice("error", error?.message || "模型高级配置保存失败");
      return false;
    } finally {
      setSubmitting(false);
    }
  }, [fetchModelState, pushNotice]);

  const handleDiscoverModels = useCallback(async (
    providerId: string,
    payload?: {
      apiKey?: string;
      baseUrl?: string;
      protocol?: string;
      generateConfigText?: string;
    },
  ) => {
    if (!providerId) {
      return false;
    }

    const parsedGenerateConfig = parseGenerateConfig(payload?.generateConfigText);
    if (!parsedGenerateConfig.ok) {
      pushNotice("error", parsedGenerateConfig.error);
      return false;
    }

    setSwitching(true);
    try {
      const response = await modelsApi.discoverModels(providerId, {
        api_key: payload?.apiKey || undefined,
        base_url: payload?.baseUrl || undefined,
        chat_model: payload?.protocol || undefined,
        generate_kwargs: parsedGenerateConfig.value,
      });
      await fetchModelState();
      pushNotice(
        response?.success ? "success" : "info",
        response?.message || `已同步 ${response?.added_count || 0} 个模型`,
      );
      return Boolean(response?.success);
    } catch (error: any) {
      pushNotice("error", error?.message || "自动获取模型失败");
      return false;
    } finally {
      setSwitching(false);
    }
  }, [fetchModelState, pushNotice]);

  return {
    resolvedAgentId,
    providers,
    displayProviders,
    eligibleProviders,
    activeProviderId,
    activeProviderName,
    activeModelId,
    activeModelLabel,
    loading,
    switching,
    submitting,
    notice,
    clearNotice,
    fetchModelState,
    handleSelectModel,
    handleConnectModel,
    handleDeleteProvider,
    handleApplyBuiltinApiKey,
    handleRemoveModel,
    handleConfigureModel,
    handleTestProvider,
    handleTestModel,
    handleDiscoverModels,
  };
}
