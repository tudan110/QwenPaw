import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createElement, type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import type { ProviderInfo } from "../../api/models";
import type { SaveProviderPayload, usePortalModels } from "./usePortalModels";
import type { ModelConfigModal } from "./modelControls";

test("one-step model setup preserves provider cards and global defaults", async (t) => {
  const originalWindow = globalThis.window;
  Object.assign(globalThis, {
    window: { setTimeout: () => 0, clearTimeout: () => {} },
  });
  const server = await createServer({
    root: fileURLToPath(new URL("../../..", import.meta.url)),
    configFile: false,
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false },
    appType: "custom",
  });
  try {
    const { usePortalModels: useModels } = await server.ssrLoadModule(
      "/src/pages/digital-employee/usePortalModels.ts",
    );
    const { modelsApi } = await server.ssrLoadModule("/src/api/models.ts");
    const providers = new Map<string, ProviderInfo>();
    const calls: string[] = [];
    let failConfig = false;
    let failModel = false;
    t.mock.method(modelsApi, "createCustomProvider", async (body) => {
      calls.push("create");
      assert.equal(providers.has(body.id), false, "never recreate a saved provider");
      const provider: ProviderInfo = {
        ...body,
        is_custom: true,
        base_url: body.default_base_url,
        models: [],
        extra_models: [],
      };
      providers.set(body.id, provider);
      return provider;
    });
    t.mock.method(modelsApi, "configureProvider", async (id, body) => {
      calls.push("configure");
      if (failConfig) throw new Error("Connection settings failed");
      const previous = providers.get(id)!;
      const provider = {
        ...previous,
        ...body,
        api_key: body.api_key ?? previous.api_key,
      };
      providers.set(id, provider);
      return provider;
    });
    t.mock.method(modelsApi, "addModel", async (id, body) => {
      calls.push("add");
      if (failModel) throw new Error("Model save failed");
      const previous = providers.get(id)!;
      const provider = {
        ...previous,
        extra_models: [...(previous.extra_models || []), body],
      };
      providers.set(id, provider);
      return provider;
    });
    t.mock.method(modelsApi, "setActiveLlm", async () => {
      assert.fail("adding a model must not change the global or agent default");
    });
    t.mock.method(modelsApi, "removeModel", async () => {
      assert.fail("saving or revoking a provider must not replace its models");
    });
    t.mock.method(modelsApi, "deleteCustomProvider", async (id) => {
      calls.push("delete");
      providers.delete(id);
      return [...providers.values()];
    });
    const setup = () => {
      let hook: ReturnType<typeof usePortalModels>;
      function Harness() {
        hook = useModels({ enabled: false });
        return null;
      }
      renderToStaticMarkup(createElement(Harness));
      return hook!;
    };
    const payload: SaveProviderPayload = {
      mode: "create",
      providerId: "custom-first",
      providerName: "测试服务",
      protocol: "AnthropicChatModel",
      baseUrl: " https://example.com/v1 ",
      apiKey: " test-key ",
      initialModelId: " claude-test ",
      generateConfigText: '{"temperature":0.2}',
    };

    await t.test("creates one provider with its first model and appends later models", async () => {
      const hook = setup();
      assert.equal(await hook.handleSaveProvider(payload), true);
      assert.deepEqual(calls.splice(0), ["create", "configure", "add"]);
      assert.equal(providers.size, 1);
      assert.equal(providers.get("custom-first")?.chat_model, "AnthropicChatModel");
      assert.equal(providers.get("custom-first")?.base_url, "https://example.com/v1");
      assert.equal(providers.get("custom-first")?.api_key, "test-key");
      assert.deepEqual(providers.get("custom-first")?.generate_kwargs, { temperature: 0.2 });
      assert.deepEqual(providers.get("custom-first")?.extra_models, [
        { id: "claude-test", name: "claude-test" },
      ]);
      assert.equal(await hook.handleAddModel({
        providerId: "custom-first", modelId: " second-model ",
      }), true);
      assert.deepEqual(calls.splice(0), ["add"]);
      assert.deepEqual(providers.get("custom-first")?.extra_models?.[1], {
        id: "second-model", name: "second-model",
      });
      assert.equal(await hook.handleSaveProvider({
        ...payload, mode: "edit", apiKey: "", initialModelId: "third-model",
      }), true);
      assert.deepEqual(calls.splice(0), ["configure", "add"]);
      assert.equal(providers.get("custom-first")?.api_key, "test-key");
      assert.equal(providers.get("custom-first")?.extra_models?.length, 3);
      assert.equal(providers.size, 1);
      assert.equal(await hook.handleSaveProvider({
        ...payload, mode: "edit", initialModelId: "third-model",
      }), false);
      assert.deepEqual(calls.splice(0), []);
    });

    await t.test("validates all required inputs and JSON before creating anything", async () => {
      const hook = setup();
      for (const invalid of [
        { providerName: " " },
        { baseUrl: " " },
        { initialModelId: " " },
        { generateConfigText: "[]" },
        { generateConfigText: "invalid" },
      ]) {
        assert.equal(await hook.handleSaveProvider({ ...payload, ...invalid }), false);
      }
      assert.deepEqual(calls.splice(0), []);
    });

    await t.test("retries partial failures without creating duplicate cards", async () => {
      for (const phase of ["config", "model"]) {
        const hook = setup();
        const next = { ...payload, providerId: `custom-retry-${phase}` };
        failConfig = phase === "config";
        failModel = phase === "model";
        assert.equal(await hook.handleSaveProvider(next), false);
        assert.deepEqual(calls.splice(0), phase === "config"
          ? ["create", "configure"] : ["create", "configure", "add"]);
        failConfig = false;
        failModel = false;
        assert.equal(await hook.handleSaveProvider(next), true);
        assert.deepEqual(calls.splice(0), ["configure", "add"]);
        assert.equal(providers.get(next.providerId)?.extra_models?.length, 1);
      }
    });

    await t.test("retains the independent provider-only creation path", async () => {
      const hook = setup();
      assert.equal(await hook.handleSaveProvider({
        mode: "create", providerId: "legacy", providerName: "Legacy",
        baseUrl: "", apiKey: "",
      }), true);
      assert.deepEqual(calls.splice(0), ["create", "configure"]);
      assert.deepEqual(providers.get("legacy")?.extra_models, []);
    });

    await t.test("former preset ID has no special model or authorization behavior", async () => {
      const hook = setup();
      const custom = { ...payload, providerId: "ct-cnos" };
      assert.equal(await hook.handleSaveProvider(custom), true);
      assert.deepEqual(calls.splice(0), ["create", "configure", "add"]);
      assert.equal(await hook.handleSaveProvider({
        ...custom, mode: "edit", initialModelId: undefined,
      }), true);
      assert.deepEqual(calls.splice(0), ["configure"]);
      assert.equal(await hook.handleRevokeProviderAuth("ct-cnos"), true);
      assert.deepEqual(calls.splice(0), ["configure"]);
      assert.equal(providers.get("ct-cnos")?.api_key, "");
      assert.deepEqual(providers.get("ct-cnos")?.extra_models, [
        { id: "claude-test", name: "claude-test" },
      ]);
      assert.equal("handleApplyBuiltinApiKey" in hook, false);
      assert.equal(await hook.handleDeleteProvider("ct-cnos"), true);
      assert.deepEqual(calls.splice(0), ["delete"]);
      assert.equal(providers.has("ct-cnos"), false);
    });

    await t.test("custom provider cards have no key acquisition or deletion exemptions", async () => {
      const { ModelConfigModal: ModelPage } = await server.ssrLoadModule(
        "/src/pages/digital-employee/modelControls.tsx",
      );
      const action = async () => true;
      const props: ComponentProps<typeof ModelConfigModal> = {
        open: true,
        activeProviderId: "",
        activeProviderName: "",
        activeModelLabel: "",
        globalActiveProviderId: "",
        globalActiveProviderName: "",
        globalActiveModelId: "",
        globalActiveModelLabel: "",
        usesGlobalDefault: true,
        eligibleProviders: [],
        displayProviders: [{
          id: "ct-cnos", name: "Custom service", isCustom: true,
          isLocal: false, baseUrl: "https://example.com/v1",
          apiKeyMasked: "", apiKeyConfigured: false, description: "",
          requireApiKey: false, supportModelDiscovery: false,
          configured: true, available: false, generateKwargs: {}, models: [],
        }],
        loading: false, switching: false, submitting: false, notice: null,
        onRefresh: () => {},
        onSelectDefaultModel: action,
        onSubmitProvider: action,
        onSubmitModel: action,
        onDeleteProvider: action,
        onRevokeProviderAuth: action,
        onRemoveModel: action,
        onTestProvider: action,
        onTestModel: action,
        onProbeMultimodal: action,
        onDiscoverModels: action,
        onConfigureModel: action,
      };
      const html = renderToStaticMarkup(createElement(ModelPage, props));
      assert.match(html, /Custom service/);
      assert.match(html, />删除<\/button>/);
      assert.match(html, />模型<\/button>/);
      assert.match(html, />设置<\/button>/);
      assert.doesNotMatch(html, /获取 API Key|builtin-api-key|portal-demo-account/);
    });
  } finally {
    await server.close();
    Object.assign(globalThis, { window: originalWindow });
  }
});
