import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import type { usePortalSessionHistory } from "./usePortalSessionHistory";

type HistoryOptions = Parameters<typeof usePortalSessionHistory>[0];

test("new conversations stay scoped to the current employee", async (t) => {
  t.mock.method(Date, "now", () => 1_800_000_000_000);
  const originalWindow = globalThis.window;
  Object.assign(globalThis, { window: {} });
  const server = await createServer({
    root: fileURLToPath(new URL("../../..", import.meta.url)),
    configFile: false,
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false },
    appType: "custom",
  });
  try {
    const { usePortalSessionHistory } = await server.ssrLoadModule(
      "/src/pages/digital-employee/usePortalSessionHistory.ts",
    );
    const { digitalEmployees } = await server.ssrLoadModule("/src/data/portalData.ts");
    const { createInitialMessages } = await server.ssrLoadModule(
      "/src/pages/digital-employee/helpers.ts",
    );
    const { PORTAL_HOME_EMPLOYEE, REMOTE_AGENT_IDS } = await server.ssrLoadModule(
      "/src/pages/digital-employee/pageHelpers.ts",
    );

    function setup(overrides: Partial<HistoryOptions>) {
      const calls = new Map<string, unknown[][]>();
      const record = (name: string) => (...args: unknown[]) => {
        calls.set(name, [...(calls.get(name) || []), args]);
      };
      const options: HistoryOptions = {
        currentEmployee: PORTAL_HOME_EMPLOYEE,
        isRemoteEmployee: true,
        isPortalHome: true,
        isPortalHomeChat: true,
        isAlarmWorkbenchMode: false,
        remoteAgentId: "gateway",
        currentChatId: "previous-chat",
        currentSessionId: "previous-session",
        activePortalResourceImportSessionId: "resource-session",
        activePortalKnowledgeBaseSessionId: "knowledge-session",
        conversationStore: {},
        setConversationStore: record("store"),
        remoteSessions: [],
        portalResourceImportSessions: [],
        portalKnowledgeBaseSessions: [],
        historyVisible: true,
        setHistoryVisible: record("history"),
        locationState: null,
        locationPathname: "/",
        locationSearch: "",
        handledDashboardSessionOpenRef: { current: "" },
        setMessages: record("messages"),
        setCurrentSessionId: record("session"),
        setCurrentChatId: record("chat"),
        setInputMessage: record("input"),
        setExecutionVisible: record("execution"),
        setPortalHomeChatMode: record("homeChat"),
        setActivePortalResourceImportSessionId: record("resource"),
        setActivePortalKnowledgeBaseSessionId: record("knowledge"),
        stopActiveStream: record("stop"),
        refreshRemoteSessions: record("refresh"),
        handleSelectRemoteHistory: async () => {},
        resetRemoteState: record("reset"),
        resetAlarmWorkbench: record("resetAlarm"),
        loadAlarmWorkorders: record("loadAlarm"),
        createAndActivateLocalSession: (...args) => {
          record("createLocal")(...args);
          return "new-local-session";
        },
        navigate: record("navigate"),
        ...overrides,
      };
      let start: (() => void) | undefined;
      function Harness() {
        start = usePortalSessionHistory(options).handleStartNewConversation;
        return null;
      }
      renderToStaticMarkup(createElement(Harness));
      assert.ok(start);
      start();
      assert.equal(calls.has("navigate"), false);
      assert.equal(calls.has("store"), false);
      for (const name of ["input", "resource", "knowledge"]) {
        assert.deepEqual(calls.get(name), [[""]], name);
      }
      assert.deepEqual(calls.get("history"), [[false]]);
      assert.deepEqual(calls.get("execution"), [[false]]);
      return calls;
    }

    for (const employee of digitalEmployees.filter(
      (item: { id: string }) => REMOTE_AGENT_IDS[item.id],
    )) {
      await t.test(`remote employee ${employee.id} keeps its welcome messages and route`, () => {
        const calls = setup({
          currentEmployee: employee,
          isPortalHome: false,
          isPortalHomeChat: false,
          remoteAgentId: REMOTE_AGENT_IDS[employee.id],
          locationPathname: `/employee/${employee.id}`,
        });
        assert.deepEqual(calls.get("reset"), [[{
          initialMessages: createInitialMessages(employee),
        }]]);
        assert.equal(calls.has("createLocal"), false);
        assert.deepEqual(calls.get("homeChat"), [[false]]);
      });
    }

    await t.test("home keeps an empty gateway conversation", () => {
      const calls = setup({});
      assert.deepEqual(calls.get("reset"), [[{ initialMessages: [] }]]);
      assert.equal(calls.has("createLocal"), false);
      assert.deepEqual(calls.get("homeChat"), [[false]]);
    });

    await t.test("local employee gets a new employee-owned session", () => {
      const employee = digitalEmployees[0];
      const calls = setup({
        currentEmployee: employee,
        isPortalHome: false,
        isPortalHomeChat: false,
        isRemoteEmployee: false,
        remoteAgentId: null,
      });
      const initialMessages = createInitialMessages(employee);
      assert.deepEqual(calls.get("createLocal"), [[employee, initialMessages]]);
      assert.deepEqual(calls.get("messages"), [[initialMessages]]);
      assert.equal(calls.has("reset"), false);
    });

    await t.test("alarm workbench restarts within the current employee", () => {
      const employee = digitalEmployees.find((item: { id: string }) => item.id === "fault");
      assert.ok(employee);
      const calls = setup({
        currentEmployee: employee,
        isPortalHome: false,
        isPortalHomeChat: false,
        isAlarmWorkbenchMode: true,
        remoteAgentId: REMOTE_AGENT_IDS[employee.id],
      });
      assert.deepEqual(calls.get("resetAlarm"), [[]]);
      assert.deepEqual(calls.get("loadAlarm"), [[]]);
      assert.equal(calls.get("reset")?.length, 1);
      assert.equal(calls.has("createLocal"), false);
    });
  } finally {
    await server.close();
    Object.assign(globalThis, { window: originalWindow });
  }
});
