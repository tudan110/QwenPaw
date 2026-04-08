import { useEffect, useRef, useState, type FormEvent, type RefObject } from "react";
import { DEFAULT_PROVIDER_SLOT_ID } from "./usePortalModels";
import type {
  AddProviderModelPayload,
  BuiltinApiKeyApplyPayload,
  BuiltinApiKeyApplyResult,
  DisplayProvider,
  EligibleProvider,
  ModelNoticeState,
  SaveProviderPayload,
} from "./usePortalModels";

type ProviderConfigFormState = {
  providerName: string;
  providerId: string;
  baseUrl: string;
  apiKey: string;
  protocol: string;
  apiKeyConfigured: boolean;
  generateConfigText: string;
  advancedOpen: boolean;
};

type AddModelFormState = {
  providerId: string;
  providerName: string;
  modelId: string;
  modelName: string;
  generateConfigText: string;
  advancedOpen: boolean;
};

const DEFAULT_PROVIDER_FORM_STATE: ProviderConfigFormState = {
  providerName: "",
  providerId: "",
  baseUrl: "",
  apiKey: "",
  protocol: "OpenAIChatModel",
  apiKeyConfigured: false,
  generateConfigText: "",
  advancedOpen: false,
};

const DEFAULT_ADD_MODEL_FORM_STATE: AddModelFormState = {
  providerId: "",
  providerName: "",
  modelId: "",
  modelName: "",
  generateConfigText: "",
  advancedOpen: false,
};

type BuiltinApiKeyFormState = BuiltinApiKeyApplyPayload;

const DEFAULT_BUILTIN_API_KEY_FORM: BuiltinApiKeyFormState = {
  quotaServiceName: "智能客服使用",
  appIds: ["qiming1.0", "deepseek3.2", "qwen3.5"],
  expirePreset: "30d",
};

const PROTOCOL_OPTIONS = [
  {
    value: "OpenAIChatModel",
    label: "OpenAI 兼容",
    description: "适合大多数标准 OpenAI 风格接口",
  },
  {
    value: "AnthropicChatModel",
    label: "Anthropic 兼容",
    description: "适用于 Claude / Anthropic 风格接口",
  },
] as const;

function ProtocolSelect({
  value,
  disabled,
  onChange,
}: {
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useOutsideClose(open, containerRef, () => setOpen(false));

  const selected = PROTOCOL_OPTIONS.find((option) => option.value === value) || PROTOCOL_OPTIONS[0];

  return (
    <div className="portal-select" ref={containerRef}>
      <button
        type="button"
        className={open ? "portal-select-trigger active" : "portal-select-trigger"}
        disabled={disabled}
        onClick={() => {
          if (!disabled) {
            setOpen((prev) => !prev);
          }
        }}
      >
        <span className="portal-select-copy">
          <span className="portal-select-title">{selected.label}</span>
        </span>
        <i className={`fas ${open ? "fa-chevron-up" : "fa-chevron-down"}`} />
      </button>

      {open ? (
        <div className="portal-select-menu">
          {PROTOCOL_OPTIONS.map((option) => {
            const active = option.value === value;
            return (
              <button
                key={option.value}
                type="button"
                className={active ? "portal-select-option active" : "portal-select-option"}
                onClick={() => {
                  onChange(option.value);
                  setOpen(false);
                }}
              >
                <span className="portal-select-title">{option.label}</span>
                <span className="portal-select-desc">{option.description}</span>
                {active ? <i className="fas fa-check" /> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

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

function buildProviderPrefill(provider: DisplayProvider): ProviderConfigFormState {
  const generateConfigText = formatGenerateConfig(provider.generateKwargs);
  return {
    providerName: provider.name,
    providerId: provider.id,
    baseUrl: provider.baseUrl,
    apiKey: "",
    protocol:
      provider.id.includes("anthropic")
      || provider.id.includes("minimax")
        ? "AnthropicChatModel"
        : "OpenAIChatModel",
    apiKeyConfigured: provider.apiKeyConfigured,
    generateConfigText,
    advancedOpen: Boolean(generateConfigText),
  };
}

function buildAddModelPrefill(provider: DisplayProvider): AddModelFormState {
  return {
    providerId: provider.id,
    providerName: provider.name,
    modelId: "",
    modelName: "",
    generateConfigText: "",
    advancedOpen: false,
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

function DeleteConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  confirmIconClass,
  submitting,
  onClose,
  onConfirm,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  confirmIconClass?: string;
  submitting: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  if (!open) {
    return null;
  }

  return (
    <div className="history-modal show" onClick={onClose}>
      <div
        className="history-content portal-confirm-dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="history-header">
          <h3>
            <i className="fas fa-triangle-exclamation" /> {title}
          </h3>
          <button className="history-close" onClick={onClose}>
            <i className="fas fa-times" />
          </button>
        </div>
        <div className="history-body portal-confirm-body">
          <div className="portal-confirm-copy">{message}</div>
          <div className="portal-model-form-actions portal-confirm-actions">
            <button
              type="button"
              className="portal-model-btn secondary"
              disabled={submitting}
              onClick={onClose}
            >
              取消
            </button>
            <button
              type="button"
              className="portal-model-btn secondary danger"
              disabled={submitting}
              onClick={onConfirm}
            >
              <i className={`fas ${submitting ? "fa-spinner fa-spin" : confirmIconClass || "fa-trash-can"}`} />
              {confirmLabel || "确认删除"}
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
  onAcquireApiKey,
  onPrefillConnect,
  onManageModels,
  onDeleteProvider,
}: {
  displayProviders: DisplayProvider[];
  activeProviderId: string;
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
          const statusClass = provider.available
            ? "available"
            : provider.configured
              ? "partial"
              : "pending";
          const badgeText = provider.available
            ? "可用（有模型）"
            : provider.configured
              ? "未就绪（无模型）"
              : "未就绪（未配置）";

          return (
            <div
              key={provider.id}
              className={[
                "portal-model-card",
                "provider-card",
                statusClass,
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
                <span className={`portal-provider-badge ${statusClass}`}>
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
                  {provider.models.slice(0, 3).map((model) => (
                    <span
                      key={`${provider.id}-${model.id}`}
                      className="portal-provider-model-chip passive"
                    >
                      {model.name || model.id}
                    </span>
                  ))}
                  {provider.models.length > 3 ? (
                    <span className="portal-provider-model-more">
                      +{provider.models.length - 3}
                    </span>
                  ) : null}
                </div>
              ) : (
                <div className="portal-provider-model-empty">
                  {provider.baseUrl || provider.apiKeyConfigured
                    ? "当前未录入模型，可在模型管理中添加模型。"
                    : "先完成提供商配置，再到模型管理中添加模型。"}
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
  open,
  saving,
  disabled,
  onSave,
}: {
  providerId: string;
  modelId: string;
  initialText: string;
  open: boolean;
  saving: boolean;
  disabled?: boolean;
  onSave: (providerId: string, modelId: string, text: string) => Promise<boolean>;
}) {
  const [text, setText] = useState(initialText);

  useEffect(() => {
    setText(initialText);
  }, [initialText]);

  const dirty = text !== initialText;

  return (
    <div className="portal-managed-model-config">
      {open ? (
        <div className="portal-managed-model-config-panel">
          <div className="portal-managed-config-hint">
            使用 JSON 配置当前模型的专属生成参数。
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
  switching,
  submitting,
  disabled,
  notice,
  onRemoveModel,
  onTestModel,
  onProbeMultimodal,
  onDiscoverModels,
  onConfigureModel,
  onClose,
  onOpenAddModel,
}: {
  provider: DisplayProvider;
  switching: boolean;
  submitting: boolean;
  disabled?: boolean;
  notice: ModelNoticeState | null;
  onRemoveModel: (providerId: string, modelId: string) => Promise<boolean>;
  onTestModel: (providerId: string, modelId: string) => Promise<boolean>;
  onProbeMultimodal: (providerId: string, modelId: string) => Promise<boolean>;
  onDiscoverModels: (providerId: string) => Promise<boolean>;
  onConfigureModel: (providerId: string, modelId: string, text: string) => Promise<boolean>;
  onClose: () => void;
  onOpenAddModel: (provider: DisplayProvider) => void;
}) {
  const [openModelConfigs, setOpenModelConfigs] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setOpenModelConfigs({});
  }, [provider.id]);

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
                const configKey = `${provider.id}-${model.id}`;
                const configOpen = Boolean(openModelConfigs[configKey]);

                return (
                <div key={configKey} className="portal-managed-model-item">
                  <div className="portal-managed-model-header">
                    <div className="portal-managed-model-copy">
                      <div className="portal-managed-model-title">
                        <strong>{model.name || model.id}</strong>
                        {model.supportsImage ? (
                          <span className="portal-managed-model-kind image">图片</span>
                        ) : null}
                        {model.supportsVideo ? (
                          <span className="portal-managed-model-kind video">视频</span>
                        ) : null}
                        {model.supportsMultimodal === false ? (
                          <span className="portal-managed-model-kind">纯文本</span>
                        ) : null}
                        {model.supportsMultimodal === null ? (
                          <span className="portal-managed-model-kind pending">未检测</span>
                        ) : null}
                        <span className="portal-managed-model-source">用户添加</span>
                      </div>
                      <span>{model.id}</span>
                    </div>
                    <div className="portal-managed-model-actions">
                      <button
                        type="button"
                        className="portal-managed-action"
                        disabled={disabled || switching}
                        onClick={() => void onProbeMultimodal(provider.id, model.id)}
                      >
                        测试多模态
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
                        className={configOpen ? "portal-managed-action icon-only active" : "portal-managed-action icon-only"}
                        disabled={disabled || submitting}
                        onClick={() =>
                          setOpenModelConfigs((prev) => ({
                            ...prev,
                            [configKey]: !prev[configKey],
                          }))
                        }
                        aria-label={configOpen ? "收起高级配置" : "展开高级配置"}
                        title={configOpen ? "收起高级配置" : "展开高级配置"}
                      >
                        <i className={`fas ${configOpen ? "fa-chevron-up" : "fa-gear"}`} />
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
                  </div>
                  <ManagedModelConfigEditor
                    providerId={provider.id}
                    modelId={model.id}
                    initialText={formatGenerateConfig(model.generateKwargs)}
                    open={configOpen}
                    saving={submitting}
                    disabled={disabled}
                    onSave={onConfigureModel}
                  />
                </div>
              )})}
            </div>
          ) : (
            <div className="portal-provider-model-empty">
              当前 Provider 暂无可管理模型，可通过“添加模型”新增模型 ID。
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
                onClick={() => onOpenAddModel(provider)}
              >
                <i className="fas fa-plus" /> 添加模型
              </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function AddModelDialog({
  open,
  form,
  submitting,
  disabled,
  notice,
  onClose,
  onSubmit,
  onChange,
}: {
  open: boolean;
  form: AddModelFormState;
  submitting: boolean;
  disabled?: boolean;
  notice: ModelNoticeState | null;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onChange: (updater: (prev: AddModelFormState) => AddModelFormState) => void;
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
            <i className="fas fa-cube" /> 添加模型
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
                <label>提供商 ID</label>
                <input value={form.providerId} disabled />
              </div>
              <div className="portal-form-group">
                <label>显示名称</label>
                <input value={form.providerName} disabled />
              </div>
            </div>

            <div className="portal-form-row">
              <div className="portal-form-group">
                <label>模型 ID</label>
                <input
                  value={form.modelId}
                  onChange={(event) =>
                    onChange((prev) => ({ ...prev, modelId: event.target.value }))
                  }
                  placeholder="例如：DeepSeek-R1-0528"
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

            <div className="portal-model-tip">
              <i className="fas fa-circle-info" />
              先保存提供商，再为该提供商单独添加可用模型。
            </div>

            <div className="portal-advanced-config">
              <button
                type="button"
                className={form.advancedOpen ? "portal-model-toggle active" : "portal-model-toggle"}
                onClick={() =>
                  onChange((prev) => ({ ...prev, advancedOpen: !prev.advancedOpen }))
                }
              >
                <i className={`fas ${form.advancedOpen ? "fa-chevron-up" : "fa-chevron-down"}`} />
                高级配置
              </button>
              {form.advancedOpen ? (
                <div className="portal-advanced-config-panel">
                  <label>Model generate_kwargs</label>
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
                onClick={onClose}
              >
                取消
              </button>
              <button
                type="submit"
                className="portal-model-btn success"
                disabled={submitting || disabled}
              >
                <i
                  className={`fas ${
                    submitting ? "fa-spinner fa-spin" : "fa-plus"
                  }`}
                />
                {submitting ? "保存中..." : "添加模型"}
              </button>
            </div>
          </form>
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
  showRevokeAuthorization,
  onClose,
  onSubmit,
  onTestProvider,
  onRevokeAuthorization,
  onChange,
}: {
  open: boolean;
  form: ProviderConfigFormState;
  submitting: boolean;
  disabled?: boolean;
  mode: "create" | "edit";
  notice: ModelNoticeState | null;
  showRevokeAuthorization?: boolean;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onTestProvider: () => void;
  onRevokeAuthorization: () => void;
  onChange: (updater: (prev: ProviderConfigFormState) => ProviderConfigFormState) => void;
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
                <label>提供商 ID</label>
                <input
                  value={form.providerId}
                  onChange={(event) =>
                    onChange((prev) => ({ ...prev, providerId: event.target.value }))
                  }
                  placeholder="可选，不填则自动生成"
                  disabled={mode === "edit"}
                />
              </div>
              <div className="portal-form-group">
                <label>显示名称</label>
                <input
                  value={form.providerName}
                  onChange={(event) =>
                    onChange((prev) => ({ ...prev, providerName: event.target.value }))
                  }
                  placeholder="例如：自定义模型服务"
                />
              </div>
            </div>

            <div className="portal-form-row">
              <div className="portal-form-group">
                <label>API Base URL</label>
                <input
                  value={form.baseUrl}
                  onChange={(event) =>
                    onChange((prev) => ({ ...prev, baseUrl: event.target.value }))
                  }
                  placeholder={mode === "create" ? "可选，创建后可稍后补充" : "https://example.com/v1"}
                />
              </div>
              <div className="portal-form-group">
                <label>API Key</label>
                <input
                  type="password"
                  value={form.apiKey}
                  onChange={(event) =>
                    onChange((prev) => ({ ...prev, apiKey: event.target.value }))
                  }
                  placeholder={
                    mode === "create"
                      ? "可选，创建后可稍后补充"
                      : form.apiKeyConfigured
                        ? "留空以保持当前密钥"
                        : "输入 API 密钥（可选）"
                  }
                />
              </div>
            </div>

            <div className="portal-form-row">
              <div className="portal-form-group">
                <label>协议</label>
                <ProtocolSelect
                  value={form.protocol}
                  disabled={submitting || disabled}
                  onChange={(value) =>
                    onChange((prev) => ({ ...prev, protocol: value }))
                  }
                />
              </div>
            </div>

            <div className="portal-advanced-config">
              <button
                type="button"
                className={form.advancedOpen ? "portal-model-toggle active" : "portal-model-toggle"}
                onClick={() =>
                  onChange((prev) => ({ ...prev, advancedOpen: !prev.advancedOpen }))
                }
              >
                <i className={`fas ${form.advancedOpen ? "fa-chevron-up" : "fa-chevron-down"}`} />
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
                    placeholder={`{\n  "temperature": 0.2,\n  "max_tokens": 4096\n}`}
                    spellCheck={false}
                  />
                  <div className="portal-model-tip" style={{ marginTop: 12 }}>
                    <i className="fas fa-circle-info" />
                    这里的配置会作为该提供商下所有模型的默认生成参数；模型级高级配置会覆盖这里的同名字段。
                  </div>
                </div>
              ) : null}
            </div>

            <div className="portal-model-tip">
              <i className="fas fa-circle-info" />
              {mode === "create"
                ? "创建提供商时 Base URL、API Key 都可先留空，模型请到“模型管理”里单独添加。"
                : "设置时需要填写 Base URL；API Key 留空则保持当前密钥。模型请到“模型管理”里单独添加。"}
            </div>

            <div className="portal-provider-config-footer">
              <div className="portal-provider-config-footer-side">
                {showRevokeAuthorization ? (
                  <button
                    type="button"
                    className="portal-model-btn secondary danger"
                    disabled={submitting || disabled}
                    onClick={onRevokeAuthorization}
                  >
                    <i className="fas fa-link-slash" /> 撤销授权
                  </button>
                ) : null}
              </div>
              <div className="portal-provider-config-footer-side portal-model-form-actions">
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
                  {submitting ? "保存中..." : mode === "create" ? "创建提供商" : "保存设置"}
                </button>
              </div>
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
  activeProviderId,
  displayProviders,
  loading,
  switching,
  submitting,
  disabled,
  notice,
  onRefresh,
  onApplyBuiltinApiKey,
  onSubmitProvider,
  onSubmitModel,
  onDeleteProvider,
  onRevokeProviderAuth,
  onRemoveModel,
  onTestProvider,
  onTestModel,
  onProbeMultimodal,
  onDiscoverModels,
  onConfigureModel,
}: {
  open: boolean;
  activeProviderId: string;
  displayProviders: DisplayProvider[];
  loading: boolean;
  switching: boolean;
  submitting: boolean;
  disabled?: boolean;
  notice: ModelNoticeState | null;
  onRefresh: () => void;
  onApplyBuiltinApiKey: (
    payload: BuiltinApiKeyApplyPayload,
  ) => Promise<BuiltinApiKeyApplyResult | null>;
  onSubmitProvider: (payload: SaveProviderPayload) => Promise<boolean>;
  onSubmitModel: (payload: AddProviderModelPayload) => Promise<boolean>;
  onDeleteProvider: (providerId: string) => Promise<boolean>;
  onRevokeProviderAuth: (providerId: string) => Promise<boolean>;
  onRemoveModel: (providerId: string, modelId: string) => Promise<boolean>;
  onTestProvider: (providerId: string, payload?: {
    apiKey?: string;
    baseUrl?: string;
    protocol?: string;
    generateConfigText?: string;
  }) => Promise<boolean>;
  onTestModel: (providerId: string, modelId: string) => Promise<boolean>;
  onProbeMultimodal: (providerId: string, modelId: string) => Promise<boolean>;
  onDiscoverModels: (providerId: string) => Promise<boolean>;
  onConfigureModel: (providerId: string, modelId: string, text: string) => Promise<boolean>;
}) {
  const [deleteConfirmState, setDeleteConfirmState] = useState<
    | null
    | { kind: "provider"; provider: DisplayProvider }
    | { kind: "model"; providerId: string; modelId: string }
    | { kind: "revoke-auth"; providerId: string; providerName: string; isActive: boolean }
  >(null);
  const [providerForm, setProviderForm] = useState<ProviderConfigFormState>(DEFAULT_PROVIDER_FORM_STATE);
  const [modelForm, setModelForm] = useState<AddModelFormState>(DEFAULT_ADD_MODEL_FORM_STATE);
  const [managedProviderId, setManagedProviderId] = useState("");
  const [providerDialogOpen, setProviderDialogOpen] = useState(false);
  const [providerDialogMode, setProviderDialogMode] = useState<"create" | "edit">("create");
  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const [builtinApiDialogOpen, setBuiltinApiDialogOpen] = useState(false);
  const [builtinApiResultOpen, setBuiltinApiResultOpen] = useState(false);
  const [builtinApiResult, setBuiltinApiResult] = useState<BuiltinApiKeyApplyResult | null>(null);
  const [builtinApiForm, setBuiltinApiForm] = useState<BuiltinApiKeyFormState>(DEFAULT_BUILTIN_API_KEY_FORM);
  const [builtinApiProviderName, setBuiltinApiProviderName] = useState("test1");

  useEffect(() => {
    if (open) {
      setDeleteConfirmState(null);
      setProviderForm(DEFAULT_PROVIDER_FORM_STATE);
      setModelForm(DEFAULT_ADD_MODEL_FORM_STATE);
      setManagedProviderId("");
      setProviderDialogOpen(false);
      setModelDialogOpen(false);
      setBuiltinApiDialogOpen(false);
      setBuiltinApiResultOpen(false);
      setBuiltinApiResult(null);
      setBuiltinApiForm(DEFAULT_BUILTIN_API_KEY_FORM);
    }
  }, [open]);

  if (!open) {
    return null;
  }

  const handleSubmitProvider = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const succeeded = await onSubmitProvider({
      mode: providerDialogMode,
      providerId: providerForm.providerId,
      providerName: providerForm.providerName,
      baseUrl: providerForm.baseUrl,
      apiKey: providerForm.apiKey,
      protocol: providerForm.protocol,
      generateConfigText: providerForm.generateConfigText,
    });
    if (succeeded) {
      setProviderForm(DEFAULT_PROVIDER_FORM_STATE);
      setProviderDialogOpen(false);
    }
  };

  const handleSubmitModel = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const succeeded = await onSubmitModel(modelForm);
    if (succeeded) {
      setModelForm(DEFAULT_ADD_MODEL_FORM_STATE);
      setModelDialogOpen(false);
    }
  };

  const handlePrefillProvider = (provider: DisplayProvider) => {
    setProviderForm(buildProviderPrefill(provider));
    setProviderDialogMode("edit");
    setProviderDialogOpen(true);
  };

  const handleOpenAddModel = (provider: DisplayProvider) => {
    setManagedProviderId(provider.id);
    setModelForm(buildAddModelPrefill(provider));
    setModelDialogOpen(true);
  };

  const managedProvider = displayProviders.find((provider) => provider.id === managedProviderId) || null;

  const handleAddProvider = () => {
    setManagedProviderId("");
    setProviderForm(DEFAULT_PROVIDER_FORM_STATE);
    setProviderDialogMode("create");
    setProviderDialogOpen(true);
  };

  const handleOpenBuiltinApiDialog = (provider: DisplayProvider) => {
    setBuiltinApiProviderName(provider.name || "内置提供商");
    setBuiltinApiForm(DEFAULT_BUILTIN_API_KEY_FORM);
    setBuiltinApiDialogOpen(true);
  };

  const handleDelete = async (provider: DisplayProvider) => {
    setDeleteConfirmState({ kind: "provider", provider });
  };

  const handleRemoveManagedModel = async (providerId: string, modelId: string) => {
    setDeleteConfirmState({ kind: "model", providerId, modelId });
    return false;
  };

  const handleConfirmDelete = async () => {
    if (!deleteConfirmState) {
      return;
    }

    if (deleteConfirmState.kind === "revoke-auth") {
      const succeeded = await onRevokeProviderAuth(deleteConfirmState.providerId);
      if (succeeded) {
        setDeleteConfirmState(null);
        setProviderDialogOpen(false);
        setProviderForm((prev) => ({
          ...prev,
          apiKey: "",
          apiKeyConfigured: false,
        }));
      }
      return;
    }

    if (deleteConfirmState.kind === "provider") {
      const succeeded = await onDeleteProvider(deleteConfirmState.provider.id);
      if (succeeded && managedProviderId === deleteConfirmState.provider.id) {
        setManagedProviderId("");
      }
      if (succeeded) {
        setDeleteConfirmState(null);
      }
      return;
    }

    const succeeded = await onRemoveModel(
      deleteConfirmState.providerId,
      deleteConfirmState.modelId,
    );
    if (succeeded) {
      setDeleteConfirmState(null);
    }
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
                onAcquireApiKey={handleOpenBuiltinApiDialog}
                onPrefillConnect={handlePrefillProvider}
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
            switching={switching}
            submitting={submitting}
            disabled={disabled}
            notice={notice}
            onRemoveModel={handleRemoveManagedModel}
            onTestModel={onTestModel}
            onProbeMultimodal={onProbeMultimodal}
            onDiscoverModels={onDiscoverModels}
            onConfigureModel={onConfigureModel}
            onClose={() => setManagedProviderId("")}
            onOpenAddModel={handleOpenAddModel}
          />
        ) : null}
        <ProviderConfigDialog
          open={providerDialogOpen}
          form={providerForm}
          submitting={submitting}
          disabled={disabled}
          mode={providerDialogMode}
          notice={notice}
          showRevokeAuthorization={providerDialogMode === "edit" && providerForm.apiKeyConfigured}
          onClose={() => setProviderDialogOpen(false)}
          onSubmit={handleSubmitProvider}
          onTestProvider={() =>
            void onTestProvider(
              providerForm.providerId || resolveProviderId(
                providerForm.providerId.trim() || providerForm.providerName,
              ),
              {
                apiKey: providerForm.apiKey,
                baseUrl: providerForm.baseUrl,
                protocol: providerForm.protocol,
                generateConfigText: providerForm.generateConfigText,
              },
            )
          }
          onRevokeAuthorization={() =>
            setDeleteConfirmState({
              kind: "revoke-auth",
              providerId: providerForm.providerId,
              providerName: providerForm.providerName,
              isActive: providerForm.providerId === activeProviderId,
            })
          }
          onChange={(updater) => setProviderForm((prev) => updater(prev))}
        />
        <AddModelDialog
          open={modelDialogOpen}
          form={modelForm}
          submitting={submitting}
          disabled={disabled}
          notice={notice}
          onClose={() => setModelDialogOpen(false)}
          onSubmit={handleSubmitModel}
          onChange={(updater) => setModelForm((prev) => updater(prev))}
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
        <DeleteConfirmDialog
          open={Boolean(deleteConfirmState)}
          title={
            deleteConfirmState?.kind === "provider"
              ? "删除提供商"
              : deleteConfirmState?.kind === "revoke-auth"
                ? "撤销授权"
                : "删除模型"
          }
          message={
            deleteConfirmState?.kind === "provider"
              ? `确认删除提供商“${deleteConfirmState.provider.name}”吗？`
              : deleteConfirmState?.kind === "revoke-auth"
                ? deleteConfirmState.isActive
                  ? `确定要移除“${deleteConfirmState.providerName}”的 API 密钥吗？当前 LLM 模型配置也将被清除。`
                  : `确定要移除“${deleteConfirmState.providerName}”的 API 密钥吗？`
                : `确认删除模型“${deleteConfirmState?.modelId || ""}”吗？`
          }
          confirmLabel={deleteConfirmState?.kind === "revoke-auth" ? "撤销授权" : "确认删除"}
          confirmIconClass={deleteConfirmState?.kind === "revoke-auth" ? "fa-link-slash" : "fa-trash-can"}
          submitting={submitting}
          onClose={() => setDeleteConfirmState(null)}
          onConfirm={() => void handleConfirmDelete()}
        />
    </div>
  );
}
