import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import {
  createChat,
  getChatHistory,
  listChats,
  stopChat,
  streamChat,
} from "../../api/copawChat";
import { getFaultDisposalHistory } from "../../api/faultDisposalBridge";
import {
  buildThinkingBlock,
  buildToolBlock,
  createAgentMessage,
  createRemoteSessionId,
  createUserMessage,
  extractCopawMessageText,
  mergeProcessBlocks,
  normalizeRemoteHistoryMessages,
  normalizeRemoteSessions,
} from "./helpers";

const COPAW_USER_ID = "default";
const COPAW_CHANNEL = "console";

function normalizeRemoteChatErrorMessage(error: any) {
  const rawMessage = String(error?.message || "").trim();
  if (
    /RemoteProtocolError|incomplete chunked read|peer closed connection/i.test(rawMessage)
  ) {
    return "模型流式连接中断，请重试当前步骤。";
  }
  return rawMessage || "请稍后重试";
}

export function useRemoteChatSession({
  currentEmployee,
  isRemoteEmployee,
  remoteAgentId,
  setMessages,
}: {
  currentEmployee: any;
  isRemoteEmployee: boolean;
  remoteAgentId: string | null;
  setMessages: Dispatch<SetStateAction<any[]>>;
}) {
  const [currentSessionId, setCurrentSessionId] = useState("");
  const [currentChatId, setCurrentChatId] = useState("");
  const [currentChatStatus, setCurrentChatStatus] = useState("idle");
  const [historyVisible, setHistoryVisible] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [remoteSessions, setRemoteSessions] = useState<any[]>([]);
  const [isCreatingChat, setIsCreatingChat] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);

  const streamAbortRef = useRef<AbortController | null>(null);
  const activeAssistantMessageIdRef = useRef<string | null>(null);
  const streamAssistantMapRef = useRef(new Map());
  const remoteHistoryRequestIdRef = useRef(0);
  const pendingContentRef = useRef(new Map());
  const pendingProcessBlocksRef = useRef(new Map());
  const flushTimerRef = useRef(0);
  const currentEmployeeRef = useRef(currentEmployee);
  const currentChatIdRef = useRef(currentChatId);
  const currentSessionIdRef = useRef(currentSessionId);
  const currentChatStatusRef = useRef(currentChatStatus);
  const isStreamingRef = useRef(isStreaming);
  const isCreatingChatRef = useRef(isCreatingChat);
  const remoteAgentIdRef = useRef(remoteAgentId);
  const isRemoteEmployeeRef = useRef(isRemoteEmployee);

  useEffect(
    () => () => {
      if (flushTimerRef.current) {
        window.clearTimeout(flushTimerRef.current);
        flushTimerRef.current = 0;
      }
      streamAbortRef.current?.abort();
    },
    [],
  );

  useEffect(() => {
    currentEmployeeRef.current = currentEmployee;
  }, [currentEmployee]);

  useEffect(() => {
    currentChatIdRef.current = currentChatId;
  }, [currentChatId]);

  useEffect(() => {
    currentSessionIdRef.current = currentSessionId;
  }, [currentSessionId]);

  useEffect(() => {
    currentChatStatusRef.current = currentChatStatus;
  }, [currentChatStatus]);

  useEffect(() => {
    isStreamingRef.current = isStreaming;
  }, [isStreaming]);

  useEffect(() => {
    isCreatingChatRef.current = isCreatingChat;
  }, [isCreatingChat]);

  useEffect(() => {
    remoteAgentIdRef.current = remoteAgentId;
  }, [remoteAgentId]);

  useEffect(() => {
    isRemoteEmployeeRef.current = isRemoteEmployee;
  }, [isRemoteEmployee]);

  const ensureAgentContainer = (employee: any) => {
    let frontendMessageId = activeAssistantMessageIdRef.current;
    if (frontendMessageId) {
      return frontendMessageId;
    }

    frontendMessageId = `agent-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    activeAssistantMessageIdRef.current = frontendMessageId;
    setMessages((prevMessages) => [
      ...prevMessages,
      createAgentMessage(employee, {
        id: frontendMessageId,
        content: "",
      }),
    ]);
    return frontendMessageId;
  };

  const ensureAssistantMessage = (backendMessageId: string, employee: any) => {
    const existingState = streamAssistantMapRef.current.get(backendMessageId);
    if (existingState) {
      return existingState;
    }

    const frontendMessageId = ensureAgentContainer(employee);
    const needsSeparator = streamAssistantMapRef.current.size > 0;

    const nextState = {
      frontendId: frontendMessageId,
      sawDelta: false,
      started: false,
      needsSeparator,
    };
    streamAssistantMapRef.current.set(backendMessageId, nextState);
    return nextState;
  };

  const scheduleStreamFlush = () => {
    if (flushTimerRef.current) {
      return;
    }

    flushTimerRef.current = window.setTimeout(() => {
      flushTimerRef.current = 0;
      flushStreamUpdates();
    }, 32) as unknown as number;
  };

  const appendToMessageContent = (
    messageId: string,
    contentPart: string,
    { prependSeparator = false }: { prependSeparator?: boolean } = {},
  ) => {
    if (!contentPart) {
      return;
    }

    const nextFragment = `${prependSeparator ? "\n\n" : ""}${contentPart}`;
    pendingContentRef.current.set(
      messageId,
      `${pendingContentRef.current.get(messageId) || ""}${nextFragment}`,
    );
    scheduleStreamFlush();
  };

  const appendProcessBlock = (messageId: string, block: any) => {
    if (!block?.content?.trim()) {
      return;
    }

    const queuedBlocks = pendingProcessBlocksRef.current.get(messageId) || [];
    if (queuedBlocks.some((item: any) => item.id === block.id)) {
      return;
    }
    pendingProcessBlocksRef.current.set(messageId, [...queuedBlocks, block]);
    scheduleStreamFlush();
  };

  const flushStreamUpdates = () => {
    if (flushTimerRef.current) {
      window.clearTimeout(flushTimerRef.current);
      flushTimerRef.current = 0;
    }

    if (
      pendingContentRef.current.size === 0 &&
      pendingProcessBlocksRef.current.size === 0
    ) {
      return;
    }

    const contentUpdates = pendingContentRef.current;
    const processBlockUpdates = pendingProcessBlocksRef.current;
    pendingContentRef.current = new Map();
    pendingProcessBlocksRef.current = new Map();

    setMessages((prevMessages) =>
      prevMessages.map((message) => {
        const nextContentPart = contentUpdates.get(message.id);
        const nextBlocks = processBlockUpdates.get(message.id);

        if (!nextContentPart && !nextBlocks?.length) {
          return message;
        }

        let nextMessage = message;

        if (nextContentPart) {
          nextMessage = {
            ...nextMessage,
            content: `${nextMessage.content || ""}${nextContentPart}`,
          };
        }

        if (nextBlocks?.length) {
          const existingBlocks = nextMessage.processBlocks || [];
          const mergedBlocks = mergeProcessBlocks(existingBlocks, nextBlocks);

          if (mergedBlocks.length !== existingBlocks.length) {
            nextMessage = { ...nextMessage, processBlocks: mergedBlocks };
          } else if (mergedBlocks !== existingBlocks) {
            nextMessage = { ...nextMessage, processBlocks: mergedBlocks };
          }
        }

        return nextMessage;
      }),
    );
  };

  const finalizePendingResponse = useCallback((fallbackText: string) => {
    flushStreamUpdates();

    if (!activeAssistantMessageIdRef.current) {
      if (fallbackText) {
        setMessages((prevMessages) => [
          ...prevMessages,
          createAgentMessage(currentEmployeeRef.current, {
            id: `agent-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            content: fallbackText,
          }),
        ]);
      }
      return;
    }

    const activeMessageId = activeAssistantMessageIdRef.current;
    setMessages((prevMessages) =>
      prevMessages.map((message) =>
        message.id === activeMessageId && !message.content
          ? {
              ...message,
              content: fallbackText,
            }
          : message,
      ),
    );
  }, [setMessages]);

  const stopActiveStream = useCallback((
    requestStop = true,
    { silent = false }: { silent?: boolean } = {},
  ) => {
    const hadActiveStream = Boolean(
      streamAbortRef.current || activeAssistantMessageIdRef.current || isStreamingRef.current,
    );
    if (requestStop && isRemoteEmployeeRef.current && currentChatIdRef.current) {
      stopChat(remoteAgentIdRef.current || undefined, currentChatIdRef.current).catch(
        () => {},
      );
    }
    flushStreamUpdates();
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
    streamAssistantMapRef.current = new Map();
    if (!silent && hadActiveStream) {
      finalizePendingResponse("本轮对话已停止。");
    }
    activeAssistantMessageIdRef.current = null;
    setIsStreaming(false);
    setCurrentChatStatus("idle");
  }, [finalizePendingResponse]);

  const refreshRemoteSessions = useCallback(async (showSpinner = true) => {
    const nextRemoteAgentId = remoteAgentIdRef.current;
    const nextEmployee = currentEmployeeRef.current;
    if (!isRemoteEmployeeRef.current || !nextRemoteAgentId || !nextEmployee) {
      return;
    }

    const requestId = Date.now();
    remoteHistoryRequestIdRef.current = requestId;
    if (showSpinner) {
      setHistoryLoading(true);
    }
    setHistoryError("");

    try {
      const chatGroups = await Promise.all(
        [COPAW_USER_ID].map((userId) =>
          listChats(nextRemoteAgentId, {
            user_id: userId,
            channel: COPAW_CHANNEL,
          }),
        ),
      );
      if (remoteHistoryRequestIdRef.current !== requestId) {
        return;
      }
      setRemoteSessions(
        normalizeRemoteSessions(chatGroups.flat(), nextEmployee.id),
      );
    } catch (error: any) {
      if (remoteHistoryRequestIdRef.current !== requestId) {
        return;
      }
      setHistoryError(error.message || "获取聊天列表失败");
    } finally {
      if (remoteHistoryRequestIdRef.current === requestId && showSpinner) {
        setHistoryLoading(false);
      }
    }
  }, []);

  const handleOpenHistory = useCallback(async () => {
    setHistoryVisible(true);
    if (isRemoteEmployeeRef.current) {
      await refreshRemoteSessions(true);
    }
  }, [refreshRemoteSessions]);

  const handleSelectRemoteHistory = useCallback(async (session: any) => {
    const nextEmployee = currentEmployeeRef.current;
    const nextRemoteAgentId = remoteAgentIdRef.current;
    if (!nextEmployee || !nextRemoteAgentId) {
      return;
    }

    stopActiveStream(false, { silent: true });
    setHistoryLoading(true);
    setHistoryError("");

    try {
      const isPortalFaultWorkbench =
        nextEmployee.id === "fault"
        && String(session?.meta?.source || "") === "portal-fault-workorder";
      let history = null;
      let nextMessages = null;

      if (isPortalFaultWorkbench) {
        try {
          const portalHistory = await getFaultDisposalHistory(session.sessionId || "");
          const portalMessages = portalHistory.messages || [];
          if (portalMessages.length) {
            history = portalHistory;
            nextMessages = portalMessages.map((message: any) =>
              message?.type === "agent"
                ? createAgentMessage(nextEmployee, {
                    ...message,
                    content: message.content || "",
                    processBlocks: message.processBlocks || [],
                    disposalOperation: message.disposalOperation,
                  })
                : {
                    id: message.id || `user-${Date.now()}`,
                    type: "user",
                    content: message.content || "",
                  },
            );
          }
        } catch {
          history = null;
        }
      }

      if (!history || !nextMessages) {
        history = await getChatHistory(nextRemoteAgentId, session.id);
        nextMessages = normalizeRemoteHistoryMessages(
          history.messages,
          nextEmployee,
          session,
        );
      }

      setCurrentChatId(session.id);
      setCurrentSessionId(session.sessionId || "");
      setCurrentChatStatus(history.status || session.status || "idle");
      setMessages(nextMessages);
      setHistoryVisible(false);
    } catch (error: any) {
      setHistoryError(error.message || "获取聊天历史失败");
    } finally {
      setHistoryLoading(false);
    }
  }, [stopActiveStream]);

  const handleRemoteStreamEvent = (event: any, employee: any) => {
    if (event.object === "response" && event.status) {
      setCurrentChatStatus(
        event.status === "completed" ? "idle" : event.status,
      );
      return;
    }

    if (event.object === "message" && event.status === "completed") {
      if (event.role === "assistant" && event.type === "reasoning") {
        const frontendMessageId = ensureAgentContainer(employee);
        appendProcessBlock(frontendMessageId, buildThinkingBlock(event));
        return;
      }

      if (event.type === "plugin_call" || event.type === "plugin_call_output") {
        const frontendMessageId = ensureAgentContainer(employee);
        appendProcessBlock(frontendMessageId, buildToolBlock(event));
        return;
      }
    }

    if (
      event.object === "message" &&
      event.role === "assistant" &&
      event.type === "message"
    ) {
      const assistantState = ensureAssistantMessage(event.id, employee);
      const finalText = extractCopawMessageText(event);
      if (event.status === "completed" && finalText && !assistantState.sawDelta) {
        appendToMessageContent(assistantState.frontendId, finalText, {
          prependSeparator: assistantState.needsSeparator && !assistantState.started,
        });
        assistantState.started = true;
      }
      return;
    }

    if (event.object === "content" && event.type === "text" && event.msg_id) {
      const assistantState = streamAssistantMapRef.current.get(event.msg_id);
      if (!assistantState) {
        return;
      }
      if (event.delta === true && event.text) {
        appendToMessageContent(assistantState.frontendId, event.text, {
          prependSeparator: assistantState.needsSeparator && !assistantState.started,
        });
        assistantState.sawDelta = true;
        assistantState.started = true;
      } else if (event.text && event.delta !== true && !assistantState.sawDelta) {
        appendToMessageContent(assistantState.frontendId, event.text, {
          prependSeparator: assistantState.needsSeparator && !assistantState.started,
        });
        assistantState.started = true;
      }
    }
  };

  const handleRemoteSendMessage = useCallback(async (
    content: string,
    {
      visibleContent = "",
      chatName = "",
      chatMeta = null,
      forceNewChat = false,
      sessionId = "",
    }: {
      visibleContent?: string;
      chatName?: string;
      chatMeta?: any;
      forceNewChat?: boolean;
      sessionId?: string;
    } = {},
  ) => {
    const nextEmployee = currentEmployeeRef.current;
    const nextRemoteAgentId = remoteAgentIdRef.current;
    if (
      !nextEmployee ||
      !nextRemoteAgentId ||
      isStreamingRef.current ||
      isCreatingChatRef.current
    ) {
      return false;
    }

    const normalizedVisibleContent = (visibleContent || content).trim();
    const userMessage = createUserMessage(normalizedVisibleContent);
    streamAssistantMapRef.current = new Map();
    activeAssistantMessageIdRef.current = null;

    setMessages((prevMessages) => [...prevMessages, userMessage]);

    const controller = new AbortController();
    streamAbortRef.current = controller;
    setIsStreaming(true);
    setCurrentChatStatus("running");

    let streamSucceeded = false;

    try {
      let ensuredChat;
      if (!forceNewChat && currentChatIdRef.current && currentSessionIdRef.current) {
        ensuredChat = {
          id: currentChatIdRef.current,
          session_id: currentSessionIdRef.current,
        };
      } else {
        setIsCreatingChat(true);
        ensuredChat = await createChat(nextRemoteAgentId, {
          name: chatName || normalizedVisibleContent,
          session_id: sessionId || createRemoteSessionId(nextEmployee.id),
          user_id: COPAW_USER_ID,
          channel: COPAW_CHANNEL,
          meta: chatMeta || undefined,
        });
      }

      setCurrentChatId(ensuredChat.id);
      setCurrentSessionId(ensuredChat.session_id);

      await streamChat(
        nextRemoteAgentId,
        {
          input: [
            {
              role: "user",
              type: "message",
              content: [
                {
                  type: "text",
                  text: content,
                  status: "created",
                },
              ],
            },
          ],
          session_id: ensuredChat.session_id,
          user_id: COPAW_USER_ID,
          channel: COPAW_CHANNEL,
          stream: true,
        },
        {
          signal: controller.signal,
          onEvent: (event) => handleRemoteStreamEvent(event, nextEmployee),
        },
      );

      finalizePendingResponse("本轮对话未返回可展示内容。");
      setCurrentChatStatus("idle");
      streamSucceeded = true;
    } catch (error: any) {
      if (controller.signal.aborted) {
        finalizePendingResponse("本轮对话已停止。");
      } else {
        finalizePendingResponse(`对话失败：${normalizeRemoteChatErrorMessage(error)}`);
        setCurrentChatStatus("idle");
      }
    } finally {
      if (streamAbortRef.current === controller) {
        streamAbortRef.current = null;
      }
      setIsCreatingChat(false);
      setIsStreaming(false);
      await refreshRemoteSessions(false);
    }

    return streamSucceeded;
  }, [refreshRemoteSessions]);

  const resetRemoteState = useCallback(({
    initialMessages = [],
    clearHistoryError = true,
  }: {
    initialMessages?: any[];
    clearHistoryError?: boolean;
  } = {}) => {
    stopActiveStream(false, { silent: true });
    setCurrentChatStatus("idle");
    setHistoryVisible(false);
    if (clearHistoryError) {
      setHistoryError("");
    }
    setRemoteSessions([]);
    setCurrentSessionId("");
    setCurrentChatId("");
    setIsCreatingChat(false);
    if (initialMessages.length) {
      setMessages(initialMessages);
    }
  }, [setMessages, stopActiveStream]);

  return {
    currentSessionId,
    setCurrentSessionId,
    currentChatId,
    setCurrentChatId,
    currentChatStatus,
    setCurrentChatStatus,
    historyVisible,
    setHistoryVisible,
    historyLoading,
    historyError,
    remoteSessions,
    isCreatingChat,
    isStreaming,
    activeAssistantMessageIdRef,
    flushTimerRef,
    handleRemoteSendMessage,
    stopActiveStream,
    refreshRemoteSessions,
    handleOpenHistory,
    handleSelectRemoteHistory,
    resetRemoteState,
  };
}
