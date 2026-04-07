import { useEffect, useRef, useState, type FormEvent, type RefObject } from "react";
import { DEFAULT_PROVIDER_SLOT_ID } from "./usePortalModels";
import type {
  BuiltinApiKeyApplyPayload,
  BuiltinApiKeyApplyResult,
  ConnectModelPayload,
  DisplayProvider,
  EligibleProvider,
  ModelNoticeState,
} from "./usePortalModels";

type ModelConfigFormState = {
  providerName: string;
  providerId: string;
  baseUrl: string;
  apiKey: string;
  modelId: string;
  modelName: string;
  protocol: string;
  setActive: boolean;
  generateConfigText: string;
  advancedOpen: boolean;
};

const DEFAULT_FORM_STATE: ModelConfigFormState = {
  providerName: "",
  providerId: "",
  baseUrl: "",
  apiKey: "",
  modelId: "",
  modelName: "",
  protocol: "OpenAIChatModel",
  setActive: true,
  generateConfigText: "",
  advancedOpen: false,
};

type BuiltinApiKeyFormState = BuiltinApiKeyApplyPayload;

const DEFAULT_BUILTIN_API_KEY_FORM: BuiltinApiKeyFormState = {
  quotaServiceName: "智能客服使用",
  appIds: ["qiming1.0", "deepseek3.2", "qwen3.5"],
  expirePreset: "30d",
};

function resolveProviderId(value: string) {
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

function useOutsideClose(
  open: boolean,
  containerRef: RefObject<HTMLElement>,
  onClose: () => void,
) {
  useEffect(() => {
    if (!open) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        onClose();
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [containerRef, onClose, open]);
}

export function AdvancedModelEntry({
  activeModelLabel,
  activeProviderName,
  isActive,
  isTokenUsageActive,
  onOpenConfig,
  onOpenTokenUsage,
}: {
  activeModelLabel: string;
  activeProviderName: string;
  isActive?: boolean;
  isTokenUsageActive?: boolean;
  onOpenConfig: () => void;
  onOpenTokenUsage: () => void;
}) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="sidebar-advanced">
      <button
        className={collapsed ? "sidebar-advanced-header collapsed" : "sidebar-advanced-header"}
        onClick={() => setCollapsed((prev) => !prev)}
      >
        <span className="sidebar-advanced-header-title">高级功能</span>
        <span className="sidebar-advanced-header-arrow">
          <i className={`fas ${collapsed ? "fa-chevron-right" : "fa-chevron-down"}`} />
        </span>
      </button>
      <div className={collapsed ? "sidebar-advanced-grid collapsed" : "sidebar-advanced-grid"}>
        <button
          className={isActive ? "sidebar-advanced-item active" : "sidebar-advanced-item"}
          onClick={onOpenConfig}
        >
          <div className="sidebar-advanced-item-icon">
            <span role="img" aria-label="model-config">
              🧠
            </span>
          </div>
          <div className="sidebar-advanced-item-name">模型配置</div>
          <div className="sidebar-advanced-item-desc">{activeProviderName}</div>
          <div className="sidebar-advanced-item-meta">{activeModelLabel}</div>
        </button>
        <button
          className={isTokenUsageActive ? "sidebar-advanced-item active" : "sidebar-advanced-item"}
          onClick={onOpenTokenUsage}
        >
          <div className="sidebar-advanced-item-icon">
            <span role="img" aria-label="token-usage">
              📊
            </span>
          </div>
          <div className="sidebar-advanced-item-name">Token统计</div>
          <div className="sidebar-advanced-item-desc">资源消耗分析</div>
          <div className="sidebar-advanced-item-meta">按模型 / 日期统计</div>
        </button>
      </div>
    </div>
  );
}

function getProviderVisual(providerId: string, providerName: string) {
  const key = `${providerId} ${providerName}`.toLowerCase();

  if (key.includes("ctyun") || key.includes("天翼")) {
    return {
      icon: "☁️",
      className: "ctyun",
    };
  }
  if (key.includes("openai")) {
    return {
      icon: "🤖",
      className: "openai",
    };
  }
  if (key.includes("anthropic") || key.includes("claude")) {
    return {
      icon: "🧠",
      className: "anthropic",
    };
  }
  if (
    key.includes("aliyun")
    || key.includes("qwen")
    || key.includes("阿里")
  ) {
    return {
      icon: "🌐",
      className: "aliyun",
    };
  }
  if (key.includes("deepseek")) {
    return {
      icon: "🔮",
      className: "deepseek",
    };
  }
  if (key.includes("glm") || key.includes("智谱")) {
    return {
      icon: "💎",
      className: "glm",
    };
  }
  if (key.includes("local") || key.includes("ollama")) {
    return {
      icon: "🏠",
      className: "local",
    };
  }

  return {
    icon: "🧩",
    className: "default",
  };
}

function buildProviderPrefill(provider: DisplayProvider): ModelConfigFormState {
  const shouldPrefillModel =
    !(
      provider.id === DEFAULT_PROVIDER_SLOT_ID
      && !provider.baseUrl
      && !provider.apiKeyConfigured
    );
  return {
    providerName: provider.name,
    providerId: provider.id,
    baseUrl: provider.baseUrl,
    apiKey: "",
    modelId: shouldPrefillModel ? provider.models[0]?.id || "" : "",
    modelName: shouldPrefillModel ? provider.models[0]?.name || "" : "",
    protocol:
      provider.id.includes("anthropic")
      || provider.id.includes("minimax")
        ? "AnthropicChatModel"
        : "OpenAIChatModel",
    setActive: true,
    generateConfigText:
      provider.generateKwargs && Object.keys(provider.generateKwargs).length > 0
        ? JSON.stringify(provider.generateKwargs, null, 2)
        : "",
    advancedOpen: Boolean(
      provider.generateKwargs && Object.keys(provider.generateKwargs).length > 0,
    ),
  };
}

function formatGenerateConfig(generateKwargs?: Record<string, unknown>) {
  return generateKwargs && Object.keys(generateKwargs).length > 0
    ? JSON.stringify(generateKwargs, null, 2)
    : "";
}

function BuiltinApiKeyDialog({
  open,
  form,
  submitting,
  providerName,
  onClose,
  onChange,
  onSubmit,
}: {
  open: boolean;
  form: BuiltinApiKeyFormState;
  submitting: boolean;
  providerName: string;
  onClose: () => void;
  onChange: (updater: (prev: BuiltinApiKeyFormState) => BuiltinApiKeyFormState) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  if (!open) {
    return null;
  }

  const appOptions = [
    { id: "qiming1.0", name: "启明1.0" },
    { id: "deepseek3.2", name: "DeepSeek3.2" },
    { id: "qwen3.5", name: "Qwen3.5" },
  ];

  return (
    <div className="history-modal show" onClick={onClose}>
      <div
        className="history-content portal-provider-config-dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="history-header">
          <h3>
            <i className="fas fa-key" /> {providerName} · 获取 API Key
          </h3>
          <button className="history-close" onClick={onClose}>
            <i className="fas fa-times" />
          </button>
        </div>
        <div className="history-body portal-provider-config-body">
          <form className="portal-model-form" onSubmit={onSubmit}>
            <div className="portal-form-group" style={{ marginBottom: 16 }}>
              <label>模型应用 *</label>
              <div className="portal-provider-model-preview" style={{ marginTop: 8 }}>
                {appOptions.map((item) => {
                  const checked = form.appIds.includes(item.id);
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className={checked ? "portal-provider-model-chip active" : "portal-provider-model-chip"}
                      onClick={() =>
                        onChange((prev) => ({
                          ...prev,
                          appIds: checked
                            ? prev.appIds.filter((id) => id !== item.id)
                            : [...prev.appIds, item.id],
                        }))
                      }
                    >
                      {item.name}
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="portal-form-group" style={{ marginBottom: 16 }}>
              <label>名称 *</label>
              <input
                value={form.quotaServiceName}
                onChange={(event) =>
                  onChange((prev) => ({ ...prev, quotaServiceName: event.target.value }))
                }
                placeholder="请输入名称"
              />
            </div>
            <div className="portal-form-group">
              <label>有效期 *</label>
              <div
                style={{
                  display: "flex",
                  gap: 28,
                  flexWrap: "wrap",
                  marginTop: 10,
                }}
              >
                {[
                  { id: "30d", label: "30天" },
                  { id: "90d", label: "90天" },
                  { id: "180d", label: "180天" },
                  { id: "forever", label: "无限期" },
                ].map((item) => (
                  <label key={item.id} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <input
                      type="radio"
                      name="builtin-expire"
                      checked={form.expirePreset === item.id}
                      onChange={() =>
                        onChange((prev) => ({
                          ...prev,
                          expirePreset: item.id as BuiltinApiKeyFormState["expirePreset"],
                        }))
                      }
                    />
                    <span>{item.label}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="portal-model-form-actions">
              <button
                type="button"
                className="portal-model-btn secondary"
                onClick={onClose}
              >
                取消
              </button>
              <button type="submit" className="portal-model-btn" disabled={submitting}>
                <i className={`fas ${submitting ? "fa-spinner fa-spin" : "fa-key"}`} />
                获取 API Key
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

function BuiltinApiKeyResultDialog({
  open,
  result,
  onClose,
}: {
  open: boolean;
  result: BuiltinApiKeyApplyResult | null;
  onClose: () => void;
}) {
  if (!open || !result) {
    return null;
  }

  const expireText = result.expireAt.startsWith("2099-")
    ? "无限期"
    : `${Math.max(1, Math.round((new Date(result.expireAt).getTime() - Date.now()) / (24 * 60 * 60 * 1000)))}天（${new Date(result.expireAt).toLocaleString("zh-CN", { hour12: false })}）`;

  return (
    <div className="history-modal show" onClick={onClose}>
      <div
        className="history-content portal-provider-config-dialog builtin-api-result-dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="history-header">
          <h3>
            <i className="fas fa-key" /> 保存你的 API Key
          </h3>
          <button className="history-close" onClick={onClose}>
            <i className="fas fa-times" />
          </button>
        </div>
        <div className="history-body portal-provider-config-body">
          <div className="builtin-api-result-key">
            <label>API Key</label>
            <div className="builtin-api-result-key-row">
              <input readOnly value={result.apiKey} />
              <button
                type="button"
                className="portal-model-btn secondary compact"
                onClick={() => void navigator.clipboard.writeText(result.apiKey)}
              >
                复制
              </button>
            </div>
          </div>
          <div className="builtin-api-result-meta">
            <div className="builtin-api-result-item">
              <span>名称</span>
              <strong>{result.serviceName}</strong>
            </div>
            <div className="builtin-api-result-item builtin-api-result-item-apps">
              <span>模型应用</span>
              <div className="portal-provider-model-preview builtin-api-result-chips">
                {result.appNames.map((name) => (
                  <span key={name} className="portal-provider-model-chip active">
                    {name}
                  </span>
                ))}
              </div>
            </div>
            <div className="builtin-api-result-item">
              <span>有效期</span>
              <strong>{expireText}</strong>
            </div>
          </div>
          <div className="portal-model-form-actions builtin-api-result-actions">
            <button type="button" className="portal-model-btn secondary" onClick={onClose}>
              关闭
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ProviderLibrary({
  displayProviders,
  activeProviderId,
  activeModelId,
  switching,
  disabled,
  onSelectModel,
  onAcquireApiKey,
  onPrefillConnect,
  onManageModels,
  onDeleteProvider,
}: {
  displayProviders: DisplayProvider[];
  activeProviderId: string;
  activeModelId: string;
  switching: boolean;
  disabled?: boolean;
  onSelectModel: (providerId: string, modelId: string) => Promise<boolean>;
  onAcquireApiKey: (provider: DisplayProvider) => void;
  onPrefillConnect: (provider: DisplayProvider) => void;
  onManageModels: (provider: DisplayProvider) => void;
  onDeleteProvider: (provider: DisplayProvider) => Promise<void>;
}) {
  if (!displayProviders.length) {
    return (
      <div className="model-library-empty">
        <i className="fas fa-circle-nodes" />
        <span>当前没有可展示的模型源，请稍后刷新重试。</span>
      </div>
    );
  }

  return (
    <div className="portal-model-grid">
      <div className="portal-model-vendor-cards provider-board">
        {displayProviders.map((provider) => {
          const providerVisual = getProviderVisual(provider.id, provider.name);
          const isActiveProvider = provider.id === activeProviderId;
          const isRecommended = provider.id === DEFAULT_PROVIDER_SLOT_ID;
          const badgeText = isActiveProvider
            ? "当前使用"
            : provider.configured
              ? provider.models.length
                ? "已接入"
                : "已配置"
              : "待配置";

          return (
            <div
              key={provider.id}
              className={[
                "portal-model-card",
                "provider-card",
                provider.configured ? "connected" : "pending",
                isActiveProvider ? "active" : "",
                isRecommended ? "recommended" : "",
              ].filter(Boolean).join(" ")}
            >
              <div className="portal-model-card-top">
                <div className={`portal-model-icon ${providerVisual.className}`}>
                  <span role="img" aria-hidden="true">
                    {providerVisual.icon}
                  </span>
                </div>
                <span className={`portal-provider-badge ${provider.configured ? "connected" : "pending"}`}>
                  {badgeText}
                </span>
              </div>

              <div className="portal-provider-card-title">
                <div className="portal-provider-card-heading">
                  <h4>{provider.name}</h4>
                  {provider.id === DEFAULT_PROVIDER_SLOT_ID ? (
                    <span className="portal-provider-default-tag">默认</span>
                  ) : null}
                </div>
                <span>
                  {provider.isLocal ? "本地模型源" : provider.isCustom ? "自定义接入" : "系统内置"}
                </span>
              </div>

              <div className="portal-provider-info">
                <div className="portal-provider-info-row">
                  <span>Base URL:</span>
                  <strong>{provider.baseUrl || "未设置"}</strong>
                </div>
                <div className="portal-provider-info-row">
                  <span>API Key:</span>
                  <strong>{provider.apiKeyConfigured ? provider.apiKeyMasked : "未设置"}</strong>
                </div>
                <div className="portal-provider-info-row">
                  <span>Model:</span>
                  <strong>{provider.models.length ? `${provider.models.length} 个模型` : "暂无模型"}</strong>
                </div>
              </div>

              {provider.models.length ? (
                <div className="portal-provider-model-preview">
                  {provider.models.slice(0, 3).map((model) => {
                    const isActive =
                      provider.id === activeProviderId && model.id === activeModelId;
                    return (
                      <button
                        key={`${provider.id}-${model.id}`}
                        className={isActive ? "portal-provider-model-chip active" : "portal-provider-model-chip"}
                        disabled={!provider.configured || disabled || switching}
                        onClick={() => void onSelectModel(provider.id, model.id)}
                      >
                        {model.name || model.id}
                      </button>
                    );
                  })}
                  {provider.models.length > 3 ? (
                    <span className="portal-provider-model-more">
                      +{provider.models.length - 3}
                    </span>
                  ) : null}
                </div>
              ) : (
                <div className="portal-provider-model-empty">
                  {provider.configured
                    ? "当前未录入模型，可在下方补充 MODEL ID。"
                    : "先完成 API 配置，配置后可直接使用现有模型。"}
                </div>
              )}

              <div className="portal-provider-card-actions">
                {provider.id === DEFAULT_PROVIDER_SLOT_ID ? (
                  <button
                    type="button"
                    className="portal-model-btn secondary compact"
                    onClick={() => onAcquireApiKey(provider)}
                  >
                    获取 API Key
                  </button>
                ) : null}
                <button
                  type="button"
                  className="portal-model-btn secondary compact"
                  onClick={() => onManageModels(provider)}
                >
                  模型
                </button>
                <button
                  type="button"
                  className="portal-model-btn secondary compact"
                  onClick={() => onPrefillConnect(provider)}
                >
                  设置
                </button>
                {provider.isCustom && provider.id !== DEFAULT_PROVIDER_SLOT_ID ? (
                  <button
                    type="button"
                    className="portal-model-btn secondary compact danger"
                    onClick={() => void onDeleteProvider(provider)}
                  >
                    删除
                  </button>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ManagedModelConfigEditor({
  providerId,
  modelId,
  initialText,
  saving,
  disabled,
  onSave,
}: {
  providerId: string;
  modelId: string;
  initialText: string;
  saving: boolean;
  disabled?: boolean;
  onSave: (providerId: string, modelId: string, text: string) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(initialText);

  useEffect(() => {
    setText(initialText);
  }, [initialText]);

  const dirty = text !== initialText;

  return (
    <div className="portal-managed-model-config">
      <button
        type="button"
        className={open ? "portal-managed-config-toggle active" : "portal-managed-config-toggle"}
        disabled={disabled || saving}
        onClick={() => setOpen((prev) => !prev)}
      >
        <i className={`fas ${open ? "fa-chevron-up" : "fa-chevron-down"}`} />
        <span>{open ? "收起高级配置" : "高级配置"}</span>
      </button>
      {open ? (
        <div className="portal-managed-model-config-panel">
          <div className="portal-managed-config-hint">
            使用 JSON 配置当前模型的专属生成参数，优先级高于 provider 级配置。
          </div>
          <textarea
            className="portal-model-json-editor"
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder={`{\n  "extra_body": {\n    "enable_thinking": false\n  },\n  "max_tokens": 2048\n}`}
            spellCheck={false}
          />
          <div className="portal-model-form-actions compact-row">
            <button
              type="button"
              className="portal-model-btn secondary compact"
              disabled={disabled || saving || !dirty}
              onClick={() => setText(initialText)}
            >
              重置
            </button>
            <button
              type="button"
              className="portal-model-btn compact"
              disabled={disabled || saving || !dirty}
              onClick={() => void onSave(providerId, modelId, text)}
            >
              <i className={`fas ${saving ? "fa-spinner fa-spin" : "fa-floppy-disk"}`} />
              保存
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ProviderModelsDialog({
  provider,
  activeProviderId,
  activeModelId,
  switching,
  submitting,
  disabled,
  notice,
  onSelectModel,
  onRemoveModel,
  onTestModel,
  onDiscoverModels,
  onConfigureModel,
  onClose,
  onOpenConfig,
}: {
  provider: DisplayProvider;
  activeProviderId: string;
  activeModelId: string;
  switching: boolean;
  submitting: boolean;
  disabled?: boolean;
  notice: ModelNoticeState | null;
  onSelectModel: (providerId: string, modelId: string) => Promise<boolean>;
  onRemoveModel: (providerId: string, modelId: string) => Promise<boolean>;
  onTestModel: (providerId: string, modelId: string) => Promise<boolean>;
  onDiscoverModels: (providerId: string) => Promise<boolean>;
  onConfigureModel: (providerId: string, modelId: string, text: string) => Promise<boolean>;
  onClose: () => void;
  onOpenConfig: (provider: DisplayProvider) => void;
}) {
  return (
    <div className="history-modal show" onClick={onClose}>
      <div
        className="history-content portal-provider-config-dialog portal-model-manage-dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="history-header">
          <h3>
            <i className="fas fa-cubes" /> {provider.name} · 模型管理
          </h3>
          <button className="history-close" onClick={onClose}>
            <i className="fas fa-times" />
          </button>
        </div>
        <div className="history-body portal-provider-config-body">
          {notice ? (
            <div className={`model-inline-notice ${notice.tone}`}>{notice.text}</div>
          ) : null}

          {provider.models.length ? (
            <div className="portal-managed-model-list">
              {provider.models.map((model) => {
                const isActive =
                  provider.id === activeProviderId && model.id === activeModelId;
                return (
                  <div key={`${provider.id}-${model.id}`} className="portal-managed-model-item">
                    <div className="portal-managed-model-copy">
                      <div className="portal-managed-model-title">
                        <strong>{model.name || model.id}</strong>
                        <span className="portal-managed-model-kind">纯文本</span>
                        <span className="portal-managed-model-source">用户添加</span>
                      </div>
                      <span>{model.id}</span>
                    </div>
                    <div className="portal-managed-model-side">
                      <div className="portal-managed-model-actions">
                        <button
                          type="button"
                          className={isActive ? "portal-managed-action active" : "portal-managed-action"}
                          disabled={disabled || switching}
                          onClick={() => void onSelectModel(provider.id, model.id)}
                        >
                          {isActive ? "当前模型" : "设为当前"}
                        </button>
                        <button
                          type="button"
                          className="portal-managed-action"
                          disabled={disabled || switching}
                          onClick={() => void onTestModel(provider.id, model.id)}
                        >
                          测试连接
                        </button>
                        <button
                          type="button"
                          className="portal-managed-action danger"
                          disabled={disabled || submitting}
                          onClick={() => void onRemoveModel(provider.id, model.id)}
                        >
                          删除
                        </button>
                      </div>
                      <ManagedModelConfigEditor
                        providerId={provider.id}
                        modelId={model.id}
                        initialText={formatGenerateConfig(model.generateKwargs)}
                        saving={submitting}
                        disabled={disabled}
                        onSave={onConfigureModel}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="portal-provider-model-empty">
              当前 Provider 暂无可管理模型，可通过“添加模型”新增 MODEL ID。
            </div>
          )}

          <div className="portal-model-form-actions modal-actions">
            {provider.supportModelDiscovery ? (
              <button
                type="button"
                className="portal-model-btn secondary"
                disabled={disabled || switching}
                onClick={() => void onDiscoverModels(provider.id)}
              >
                <i className={`fas ${switching ? "fa-spinner fa-spin" : "fa-rotate"}`} /> 自动获取模型
              </button>
            ) : null}
            <button
              type="button"
              className="portal-model-btn secondary"
              disabled={disabled}
              onClick={() => onOpenConfig(provider)}
            >
              <i className="fas fa-plus" /> 添加模型
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ProviderConfigDialog({
  open,
  form,
  submitting,
  disabled,
  mode,
  notice,
  onClose,
  onSubmit,
  onTestProvider,
  onChange,
}: {
  open: boolean;
  form: ModelConfigFormState;
  submitting: boolean;
  disabled?: boolean;
  mode: "create" | "edit";
  notice: ModelNoticeState | null;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onTestProvider: () => void;
  onChange: (updater: (prev: ModelConfigFormState) => ModelConfigFormState) => void;
}) {
  if (!open) {
    return null;
  }

  return (
    <div className="history-modal show" onClick={onClose}>
      <div
        className="history-content portal-provider-config-dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="history-header">
          <h3>
            <i className="fas fa-sliders" /> {mode === "create" ? "添加提供商" : "提供商设置"}
          </h3>
          <button className="history-close" onClick={onClose}>
            <i className="fas fa-times" />
          </button>
        </div>
        <div className="history-body portal-provider-config-body">
          {notice ? (
            <div className={`model-inline-notice ${notice.tone}`}>{notice.text}</div>
          ) : null}
          <form className="portal-model-form" onSubmit={onSubmit}>
            <div className="portal-form-row">
              <div className="portal-form-group">
                <label>模型提供商</label>
                <input
                  value={form.providerName}
                  onChange={(event) =>
                    onChange((prev) => ({ ...prev, providerName: event.target.value }))
                  }
                  placeholder="例如：天翼开放平台"
                />
              </div>
              <div className="portal-form-group">
                <label>Provider ID</label>
                <input
                  value={form.providerId}
                  onChange={(event) =>
                    onChange((prev) => ({ ...prev, providerId: event.target.value }))
                  }
                  placeholder="可选，不填则自动生成"
                />
              </div>
            </div>

            <div className="portal-form-row">
              <div className="portal-form-group">
                <label>API Key</label>
                <input
                  type="password"
                  value={form.apiKey}
                  onChange={(event) =>
                    onChange((prev) => ({ ...prev, apiKey: event.target.value }))
                  }
                  placeholder="请输入模型服务的 API Key"
                />
              </div>
              <div className="portal-form-group">
                <label>API Base URL</label>
                <input
                  value={form.baseUrl}
                  onChange={(event) =>
                    onChange((prev) => ({ ...prev, baseUrl: event.target.value }))
                  }
                  placeholder="https://example.com/v1"
                />
              </div>
            </div>

            <div className="portal-form-row">
              <div className="portal-form-group">
                <label>MODEL ID</label>
                <input
                  value={form.modelId}
                  onChange={(event) =>
                    onChange((prev) => ({ ...prev, modelId: event.target.value }))
                  }
                  placeholder="例如：06b788a..."
                />
              </div>
              <div className="portal-form-group">
                <label>模型名称</label>
                <input
                  value={form.modelName}
                  onChange={(event) =>
                    onChange((prev) => ({ ...prev, modelName: event.target.value }))
                  }
                  placeholder="展示名称，可选"
                />
              </div>
            </div>

            <div className="portal-form-row">
              <div className="portal-form-group">
                <label>请求格式</label>
                <select
                  value={form.protocol}
                  onChange={(event) =>
                    onChange((prev) => ({ ...prev, protocol: event.target.value }))
                  }
                >
                  <option value="OpenAIChatModel">OpenAI 兼容</option>
                  <option value="AnthropicChatModel">Anthropic 兼容</option>
                </select>
              </div>
              <div className="portal-form-group">
                <label>接入后动作</label>
                <button
                  type="button"
                  className={form.setActive ? "portal-model-toggle active" : "portal-model-toggle"}
                  onClick={() => onChange((prev) => ({ ...prev, setActive: !prev.setActive }))}
                >
                  <i className={`fas ${form.setActive ? "fa-check" : "fa-circle"}`} />
                  {form.setActive ? "设为当前会话模型" : "仅保存，不切换"}
                </button>
              </div>
            </div>

            <div className="portal-model-tip">
              <i className="fas fa-circle-info" />
              OpenAI 兼容地址通常只需要填 URL、API Key 和 MODEL ID 即可。
            </div>

            <div className="portal-advanced-config">
              <button
                type="button"
                className={form.advancedOpen ? "portal-model-toggle active" : "portal-model-toggle"}
                onClick={() =>
                  onChange((prev) => ({ ...prev, advancedOpen: !prev.advancedOpen }))
                }
              >
                <i className={`fas ${form.advancedOpen ? "fa-chevron-down" : "fa-chevron-right"}`} />
                高级配置
              </button>
              {form.advancedOpen ? (
                <div className="portal-advanced-config-panel">
                  <label>Provider generate_kwargs</label>
                  <textarea
                    className="portal-model-json-editor"
                    value={form.generateConfigText}
                    onChange={(event) =>
                      onChange((prev) => ({ ...prev, generateConfigText: event.target.value }))
                    }
                    placeholder={`{\n  "extra_body": {\n    "enable_thinking": false\n  },\n  "max_tokens": 2048\n}`}
                    spellCheck={false}
                  />
                </div>
              ) : null}
            </div>

            <div className="portal-model-form-actions">
              <button
                type="button"
                className="portal-model-btn secondary"
                disabled={submitting || disabled}
                onClick={onTestProvider}
              >
                <i className="fas fa-plug-circle-check" /> 测试连接
              </button>
              <button
                type="submit"
                className="portal-model-btn success"
                disabled={submitting || disabled}
              >
                <i
                  className={`fas ${
                    submitting ? "fa-spinner fa-spin" : "fa-plug-circle-plus"
                  }`}
                />
                {submitting ? "保存中..." : mode === "create" ? "创建并保存" : "保存设置"}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

export function ChatModelSelector({
  activeModelLabel,
  activeProviderId,
  activeModelId,
  eligibleProviders,
  loading,
  switching,
  disabled,
  notice,
  onSelectModel,
  onOpenConfig,
}: {
  activeModelLabel: string;
  activeProviderId: string;
  activeModelId: string;
  eligibleProviders: EligibleProvider[];
  loading: boolean;
  switching: boolean;
  disabled?: boolean;
  notice: ModelNoticeState | null;
  onSelectModel: (providerId: string, modelId: string) => Promise<boolean>;
  onOpenConfig: () => void;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useOutsideClose(open, containerRef, () => setOpen(false));

  return (
    <div className="model-selector-wrap" ref={containerRef}>
      <button
        className={open ? "model-selector-trigger active" : "model-selector-trigger"}
        disabled={disabled}
        onClick={() => {
          if (!disabled) {
            setOpen((prev) => !prev);
          }
        }}
      >
        <span className="model-selector-trigger-copy">
          <i className="fas fa-cube" />
          <span className="model-selector-trigger-text">{activeModelLabel}</span>
        </span>
        <i className={`fas ${open ? "fa-chevron-up" : "fa-chevron-down"}`} />
      </button>

      {open ? (
        <div className="model-selector-panel">
          <div className="model-selector-panel-head">
            <div>
              <strong>当前会话模型</strong>
              <span>切换后将在下一轮消息中生效</span>
            </div>
            <button
              className="model-panel-link"
              onClick={() => {
                setOpen(false);
                onOpenConfig();
              }}
            >
              模型配置
            </button>
          </div>

          {loading ? (
            <div className="model-selector-empty">
              <i className="fas fa-spinner fa-spin" />
              <span>正在加载模型列表...</span>
            </div>
          ) : eligibleProviders.length ? (
            <div className="model-selector-groups">
              {eligibleProviders.map((provider) => (
                <div key={provider.id} className="model-selector-group">
                  <div className="model-selector-group-head">
                    <strong>{provider.name}</strong>
                    <span>{provider.description}</span>
                  </div>
                  <div className="model-selector-tags">
                    {provider.models.map((model) => {
                      const isActive =
                        provider.id === activeProviderId && model.id === activeModelId;
                      return (
                        <button
                          key={`${provider.id}-${model.id}`}
                          className={isActive ? "model-chip active" : "model-chip"}
                          disabled={disabled || switching}
                          onClick={async () => {
                            const succeeded = await onSelectModel(provider.id, model.id);
                            if (succeeded) {
                              setOpen(false);
                            }
                          }}
                        >
                          <span>{model.name || model.id}</span>
                          {isActive ? <i className="fas fa-check" /> : null}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="model-selector-empty">
              <i className="fas fa-circle-nodes" />
              <span>当前还没有可切换的模型，请先在模型配置中接入。</span>
            </div>
          )}

          {notice ? (
            <div className={`model-inline-notice ${notice.tone}`}>{notice.text}</div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function ModelConfigModal({
  open,
  resolvedAgentId,
  resolvedAgentLabel,
  activeProviderName,
  activeModelLabel,
  activeProviderId,
  activeModelId,
  displayProviders,
  eligibleProviders,
  loading,
  switching,
  submitting,
  disabled,
  notice,
  onRefresh,
  onSelectModel,
  onApplyBuiltinApiKey,
  onSubmitConnect,
  onDeleteProvider,
  onRemoveModel,
  onTestProvider,
  onTestModel,
  onDiscoverModels,
  onConfigureModel,
}: {
  open: boolean;
  resolvedAgentId: string;
  resolvedAgentLabel?: string;
  activeProviderName: string;
  activeModelLabel: string;
  activeProviderId: string;
  activeModelId: string;
  displayProviders: DisplayProvider[];
  eligibleProviders: EligibleProvider[];
  loading: boolean;
  switching: boolean;
  submitting: boolean;
  disabled?: boolean;
  notice: ModelNoticeState | null;
  onRefresh: () => void;
  onSelectModel: (providerId: string, modelId: string) => Promise<boolean>;
  onApplyBuiltinApiKey: (
    payload: BuiltinApiKeyApplyPayload,
  ) => Promise<BuiltinApiKeyApplyResult | null>;
  onSubmitConnect: (payload: ConnectModelPayload) => Promise<boolean>;
  onDeleteProvider: (providerId: string) => Promise<boolean>;
  onRemoveModel: (providerId: string, modelId: string) => Promise<boolean>;
  onTestProvider: (providerId: string, payload?: {
    apiKey?: string;
    baseUrl?: string;
    protocol?: string;
    modelId?: string;
    generateConfigText?: string;
  }) => Promise<boolean>;
  onTestModel: (providerId: string, modelId: string) => Promise<boolean>;
  onDiscoverModels: (providerId: string) => Promise<boolean>;
  onConfigureModel: (providerId: string, modelId: string, text: string) => Promise<boolean>;
}) {
  const [form, setForm] = useState<ModelConfigFormState>(DEFAULT_FORM_STATE);
  const [managedProviderId, setManagedProviderId] = useState("");
  const [configDialogOpen, setConfigDialogOpen] = useState(false);
  const [configDialogMode, setConfigDialogMode] = useState<"create" | "edit">("create");
  const [builtinApiDialogOpen, setBuiltinApiDialogOpen] = useState(false);
  const [builtinApiResultOpen, setBuiltinApiResultOpen] = useState(false);
  const [builtinApiResult, setBuiltinApiResult] = useState<BuiltinApiKeyApplyResult | null>(null);
  const [builtinApiForm, setBuiltinApiForm] = useState<BuiltinApiKeyFormState>(DEFAULT_BUILTIN_API_KEY_FORM);
  const [builtinApiProviderName, setBuiltinApiProviderName] = useState("test1");

  useEffect(() => {
    if (open) {
      setForm(DEFAULT_FORM_STATE);
      setManagedProviderId("");
      setConfigDialogOpen(false);
      setBuiltinApiDialogOpen(false);
      setBuiltinApiResultOpen(false);
      setBuiltinApiResult(null);
      setBuiltinApiForm(DEFAULT_BUILTIN_API_KEY_FORM);
    }
  }, [open]);

  if (!open) {
    return null;
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const succeeded = await onSubmitConnect(form);
    if (succeeded) {
      setForm(DEFAULT_FORM_STATE);
      setConfigDialogOpen(false);
    }
  };

  const handlePrefillConnect = (provider: DisplayProvider) => {
    setForm(buildProviderPrefill(provider));
    setConfigDialogMode("edit");
    setConfigDialogOpen(true);
  };

  const managedProvider = displayProviders.find((provider) => provider.id === managedProviderId) || null;

  const handleAddProvider = () => {
    setManagedProviderId("");
    setForm(DEFAULT_FORM_STATE);
    setConfigDialogMode("create");
    setConfigDialogOpen(true);
  };

  const handleOpenBuiltinApiDialog = (provider: DisplayProvider) => {
    setBuiltinApiProviderName(provider.name || "内置提供商");
    setBuiltinApiForm(DEFAULT_BUILTIN_API_KEY_FORM);
    setBuiltinApiDialogOpen(true);
  };

  const handleDelete = async (provider: DisplayProvider) => {
    if (!window.confirm(`确认删除提供商 ${provider.name} 吗？`)) {
      return;
    }

    const succeeded = await onDeleteProvider(provider.id);
    if (succeeded && managedProviderId === provider.id) {
      setManagedProviderId("");
    }
  };

  const handleRemoveManagedModel = async (providerId: string, modelId: string) => {
    if (!window.confirm(`确认删除模型 ${modelId} 吗？`)) {
      return false;
    }

    const succeeded = await onRemoveModel(providerId, modelId);
    return succeeded;
  };

  const handleSubmitBuiltinApiKey = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const result = await onApplyBuiltinApiKey(builtinApiForm);
    if (!result) {
      return;
    }
    setBuiltinApiDialogOpen(false);
    setBuiltinApiResult(result);
    setBuiltinApiResultOpen(true);
  };

  return (
    <div className="model-config-page">
      <div className="model-config-body">
        <div className="model-config-static">
          <div className="portal-model-page-header">
            <div className="portal-model-page-title">
              模型配置 <small>AI模型管理</small>
            </div>
            <div className="portal-model-page-actions">
              <button className="portal-model-btn" onClick={handleAddProvider}>
                <i className="fas fa-plus" /> 添加提供商
              </button>
              <button className="portal-model-btn" onClick={onRefresh}>
                <i className={`fas ${loading ? "fa-spinner fa-spin" : "fa-rotate-right"}`} /> 刷新
              </button>
            </div>
          </div>

          <div className="portal-model-scope-bar">
            <span>当前作用域：{resolvedAgentLabel || resolvedAgentId}</span>
            <span>当前模型：{activeProviderName} / {activeModelLabel}</span>
          </div>

          {notice ? (
            <div className={`model-inline-notice ${notice.tone}`}>{notice.text}</div>
          ) : null}

        </div>
        <div className="model-config-scroll">
          <div className="portal-model-shell">
            <section>
              <div className="portal-model-block-head">
                <div>
                  <h4>模型列表</h4>
                </div>
              </div>

              <ProviderLibrary
                displayProviders={displayProviders}
                activeProviderId={activeProviderId}
                activeModelId={activeModelId}
                switching={switching}
                disabled={disabled}
                onSelectModel={onSelectModel}
                onAcquireApiKey={handleOpenBuiltinApiDialog}
                onPrefillConnect={handlePrefillConnect}
                onManageModels={(provider) => setManagedProviderId(provider.id)}
                onDeleteProvider={handleDelete}
              />
            </section>
          </div>
        </div>
      </div>
        {managedProvider ? (
          <ProviderModelsDialog
            provider={managedProvider}
            activeProviderId={activeProviderId}
            activeModelId={activeModelId}
            switching={switching}
            submitting={submitting}
            disabled={disabled}
            notice={notice}
            onSelectModel={onSelectModel}
            onRemoveModel={handleRemoveManagedModel}
            onTestModel={onTestModel}
            onDiscoverModels={onDiscoverModels}
            onConfigureModel={onConfigureModel}
            onClose={() => setManagedProviderId("")}
            onOpenConfig={handlePrefillConnect}
          />
        ) : null}
        <ProviderConfigDialog
          open={configDialogOpen}
          form={form}
          submitting={submitting}
          disabled={disabled}
          mode={configDialogMode}
          notice={notice}
          onClose={() => setConfigDialogOpen(false)}
          onSubmit={handleSubmit}
          onTestProvider={() =>
            void onTestProvider(
              form.providerId || resolveProviderId(
                form.providerId.trim() || form.providerName || form.modelId,
              ),
              {
                apiKey: form.apiKey,
                baseUrl: form.baseUrl,
                protocol: form.protocol,
                modelId: form.modelId,
                generateConfigText: form.generateConfigText,
              },
            )
          }
          onChange={(updater) => setForm((prev) => updater(prev))}
        />
        <BuiltinApiKeyDialog
          open={builtinApiDialogOpen}
          form={builtinApiForm}
          submitting={submitting}
          providerName={builtinApiProviderName}
          onClose={() => setBuiltinApiDialogOpen(false)}
          onChange={(updater) => setBuiltinApiForm((prev) => updater(prev))}
          onSubmit={handleSubmitBuiltinApiKey}
        />
        <BuiltinApiKeyResultDialog
          open={builtinApiResultOpen}
          result={builtinApiResult}
          onClose={() => setBuiltinApiResultOpen(false)}
        />
    </div>
  );
}
