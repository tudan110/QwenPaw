import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import type { McpClientInfo } from "../../api/mcp";

test("MCP edit modes preserve drafts without validating a save", async (t) => {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", { configurable: true, value: {} });
  const server = await createServer({
    root: fileURLToPath(new URL("../../..", import.meta.url)),
    configFile: false,
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false },
    appType: "custom",
  });
  try {
    const { buildFormDraftJson, parseJsonFormDraft, parseEditableJson } =
      await server.ssrLoadModule("/src/pages/digital-employee/mcpPanel.tsx");

    await t.test("untouched new form can switch to JSON and back", () => {
      const form = parseJsonFormDraft("");
      const json = buildFormDraftJson(form);
      assert.equal(JSON.parse(json).key, "");
      assert.equal(JSON.parse(json).transport, "streamable_http");
      assert.equal("tools" in JSON.parse(json), false);
      assert.deepEqual(parseJsonFormDraft(json, form), form);
      assert.deepEqual(parseJsonFormDraft("", form), form);
    });

    await t.test("partial and inactive protocol fields survive repeated switches", () => {
      for (const transport of ["streamable_http", "sse", "stdio"]) {
        const form = {
          ...parseJsonFormDraft(""),
          clientKey: "draft", name: "", transport, enabled: false,
          url: "https://example.invalid/mcp", command: "",
          headersText: "Authorization=******\nX-Test=one",
          argsText: "--test\nvalue", envText: "API_KEY=******\nVALUE=one=two",
          cwd: "/opt/mcp", description: "未完成草稿",
        };
        let current = form;
        for (let i = 0; i < 3; i += 1) {
          current = parseJsonFormDraft(buildFormDraftJson(current), current);
          assert.deepEqual(current, form);
        }
        assert.deepEqual(parseJsonFormDraft("", form), form);
        assert.deepEqual(parseJsonFormDraft("{}", form), form);
      }
    });

    await t.test("standard single-client JSON imports use the same form shape", () => {
      for (const config of [
        { command: "npx", args: ["-y", "example"], env: { TOKEN: "******" } },
        { transport: "sse", url: "https://example.invalid/sse", headers: { TOKEN: "******" } },
        { url: "https://example.invalid/mcp", enabled: false },
      ]) {
        const form = parseJsonFormDraft(JSON.stringify({ mcpServers: { example: config } }));
        assert.equal(form.clientKey, "example");
        assert.equal(form.name, "example");
        assert.deepEqual(parseJsonFormDraft(buildFormDraftJson(form), form), form);
      }
    });

    await t.test("multiple clients cannot silently collapse into one form", () => {
      const text = JSON.stringify({ mcpServers: {
        one: { command: "one" }, two: { command: "two" },
      } });
      assert.throws(() => parseJsonFormDraft(text), /表单模式仅支持一个/);
    });

    await t.test("invalid JSON or field types do not mutate the last form draft", () => {
      const form = { ...parseJsonFormDraft(""), name: "保留草稿" };
      const previous = { ...form };
      for (const value of [
        "{", "[]", "null", '{"name":123}', '{"enabled":"false"}',
        '{"args":"--test"}', '{"headers":[]}', '{"env":{"KEY":123}}',
      ]) {
        assert.throws(() => parseJsonFormDraft(value, form));
        assert.deepEqual(form, previous);
      }
      assert.throws(() => parseEditableJson(""), /JSON 格式无效/);
    });

    await t.test("existing keys, masked credentials and tool selection remain intact", () => {
      const client: McpClientInfo = {
        key: "existing", name: "Original", description: "", enabled: true,
        transport: "sse", url: "https://example.invalid/sse",
        headers: { TOKEN: "******" }, command: "", args: [],
        env: {}, cwd: "", tools: ["read"],
      };
      const form = parseJsonFormDraft(JSON.stringify(client));
      const updated = parseJsonFormDraft('{"name":"Updated"}', form, client);
      assert.equal(updated.clientKey, client.key);
      assert.equal(updated.url, client.url);
      assert.equal(updated.headersText, "TOKEN=******");
      assert.equal(JSON.parse(buildFormDraftJson(updated, null)).tools, null);
      assert.deepEqual(JSON.parse(buildFormDraftJson(updated, client.tools)).tools, ["read"]);
      assert.throws(() => parseJsonFormDraft('{"key":"other"}', form, client), /不可修改/);
    });
  } finally {
    await server.close();
    if (originalWindow) Object.defineProperty(globalThis, "window", originalWindow);
    else Reflect.deleteProperty(globalThis, "window");
  }
});
