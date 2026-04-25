import { useCallback, useMemo } from "react";
import {
  AgentScopeRuntimeWebUI,
  type IAgentScopeRuntimeWebUIOptions,
} from "@agentscope-ai/chat";
import { App as AntdApp } from "antd";
import { ConfigProvider, bailianTheme } from "@agentscope-ai/design";
import { theme as antdTheme } from "antd";
import { createPortalRuntimeSessionApi } from "../lib/portalRuntimeSessionApi";
import { stopChat } from "../api/copawChat";
import PortalStreamingResponseCard from "./PortalStreamingResponseCard";

const DEFAULT_API_BASE_URL = "/copaw-api/api";
const API_BASE_URL = (import.meta.env.VITE_COPAW_API_BASE_URL || DEFAULT_API_BASE_URL).replace(
  /\/$/,
  "",
);
const DEFAULT_USER_ID = "default";
const DEFAULT_CHANNEL = "console";

function extractUserMessageText(message: any): string {
  const content = Array.isArray(message?.content) ? message.content : [];
  return content
    .filter((item: any) => item?.type === "text")
    .map((item: any) => String(item?.text || ""))
    .join("\n")
    .trim();
}

export function PortalRemoteRuntimeChat({
  agentId,
  agentName,
  isDark = false,
}: {
  agentId?: string | null;
  agentName: string;
  isDark?: boolean;
}) {
  const sessionApi = useMemo(() => createPortalRuntimeSessionApi(agentId || undefined), [agentId]);

  const customFetch = useCallback(
    async (data: {
      input?: Array<Record<string, unknown>>;
      biz_params?: Record<string, unknown>;
      signal?: AbortSignal;
    }): Promise<Response> => {
      const { input = [], biz_params } = data;
      const lastMessage = input[input.length - 1] as Record<string, any> | undefined;
      const session: Record<string, any> = (lastMessage?.session || {}) as Record<string, any>;
      const lastInput = input.slice(-1);
      const sessionContext = sessionApi.getSessionContext(String(session?.session_id || ""));
      const requestSessionId = sessionContext.sessionId || String(session?.session_id || "");
      const requestBody = {
        input: lastInput,
        session_id: requestSessionId,
        user_id: sessionContext.userId || session?.user_id || DEFAULT_USER_ID,
        channel: sessionContext.channel || session?.channel || DEFAULT_CHANNEL,
        stream: true,
        ...biz_params,
      };

      const backendChatId =
        sessionContext.realId ||
        requestBody.session_id;

      if (backendChatId) {
        const userText = lastInput
          .filter((message: any) => message.role === "user")
          .map(extractUserMessageText)
          .join("\n")
          .trim();
        if (userText) {
          sessionApi.setLastUserMessage(backendChatId, userText);
        }
      }

      return fetch(`${API_BASE_URL}/console/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(agentId ? { "X-Agent-Id": agentId } : {}),
        },
        body: JSON.stringify(requestBody),
        signal: data.signal,
      });
    },
    [agentId, sessionApi],
  );

  const options = useMemo(
    () =>
      ({
        theme: {
          colorPrimary: "#FF7F16",
          darkMode: isDark,
          prefix: "qwenpaw",
          leftHeader: {
            logo: "",
            title: `${agentName}`,
          },
        },
        sender: {
          maxLength: 10000,
          placeholder: `向 ${agentName} 描述您的需求...`,
        },
        welcome: {
          greeting: `你好，我是 ${agentName}`,
          description: "当前聊天区已切换为 QwenPaw 原生流式前端链路。",
          prompts: [],
        },
        session: {
          multiple: true,
          hideBuiltInSessionList: false,
          api: sessionApi,
        },
        cards: {
          AgentScopeRuntimeResponseCard: PortalStreamingResponseCard,
        },
        api: {
          fetch: customFetch,
          cancel(data: { session_id: string }) {
            const chatId =
              sessionApi.getRealIdForSession(data.session_id) ?? data.session_id;
            if (chatId) {
              stopChat(agentId || undefined, chatId).catch(() => {});
            }
          },
          async reconnect(data: { session_id: string; signal?: AbortSignal }) {
            const sessionContext = sessionApi.getSessionContext(data.session_id);
            return fetch(`${API_BASE_URL}/console/chat`, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                ...(agentId ? { "X-Agent-Id": agentId } : {}),
              },
              body: JSON.stringify({
                reconnect: true,
                session_id: sessionContext.sessionId || data.session_id,
                user_id: sessionContext.userId || DEFAULT_USER_ID,
                channel: sessionContext.channel || DEFAULT_CHANNEL,
              }),
              signal: data.signal,
            });
          },
        },
      }) as unknown as IAgentScopeRuntimeWebUIOptions,
    [agentId, agentName, customFetch, isDark, sessionApi],
  );

  return (
    <div className="portal-runtime-chat-shell">
      <ConfigProvider
        {...bailianTheme}
        prefix="qwenpaw"
        prefixCls="qwenpaw"
        theme={{
          ...(bailianTheme as any)?.theme,
          algorithm: isDark
            ? antdTheme.darkAlgorithm
            : antdTheme.defaultAlgorithm,
          token: {
            colorPrimary: "#FF7F16",
          },
        }}
      >
        <AntdApp>
          <AgentScopeRuntimeWebUI options={options} />
        </AntdApp>
      </ConfigProvider>
    </div>
  );
}
