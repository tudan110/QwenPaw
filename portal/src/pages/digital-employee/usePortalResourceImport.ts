import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { digitalEmployees } from "../../data/portalData";
import { submitResourceImport } from "../../api/resourceImport";
import { saveConversationStore } from "../../lib/conversationStore";
import {
  buildEmployeePagePath,
  type PortalAdvancedPanel,
  type PortalView,
} from "./helpers";
import {
  RESOURCE_IMPORT_COMMAND,
  RESOURCE_IMPORT_OWNER_ID,
  buildResourceImportSessionRecord,
  createResourceImportFlowId,
  ensureObjectArray,
  ensureSessionRecords,
  isPortalResourceImportSession,
} from "./pageHelpers";
import type {
  ConversationStoreState,
  PortalLocationState,
  SessionRecord,
} from "./pageHelpers";

type MessageRecord = { id: string; resourceImportFlow?: Record<string, any> } & Record<string, any>;

type NavigateToEmployeePage = (
  employee: any,
  options?: {
    entry?: string | null;
    view?: PortalView;
    panel?: PortalAdvancedPanel | null;
    replace?: boolean;
    state?: PortalLocationState;
  },
) => void;

export function usePortalResourceImport({
  conversationStore,
  setConversationStore,
  messages,
  setMessages,
  selectedEmployeeId,
  remoteAgentId,
  navigateToEmployeePage,
  setCurrentChatId,
  createAgentMessage,
  createUserMessage,
}: {
  conversationStore: ConversationStoreState;
  setConversationStore: React.Dispatch<React.SetStateAction<ConversationStoreState>>;
  messages: MessageRecord[];
  setMessages: React.Dispatch<React.SetStateAction<MessageRecord[]>>;
  selectedEmployeeId?: string;
  remoteAgentId: string | null;
  navigateToEmployeePage: NavigateToEmployeePage;
  setCurrentChatId: React.Dispatch<React.SetStateAction<string>>;
  createAgentMessage: (employee: any, payload: Record<string, any>) => MessageRecord;
  createUserMessage: (content: string) => MessageRecord;
}) {
  const resourceImportFilesRef = useRef<Map<string, File[]>>(new Map());
  const [activePortalResourceImportSessionId, setActivePortalResourceImportSessionId] = useState("");

  const resourceImportEmployee = useMemo(
    () => digitalEmployees.find((item) => item.id === RESOURCE_IMPORT_OWNER_ID) || null,
    [],
  );

  const upsertPortalSession = useCallback((
    employeeId: string,
    nextSession: SessionRecord,
  ) => {
    setConversationStore((prevStore) => {
      const previousSessions = ensureSessionRecords(prevStore[employeeId]);
      const currentSession = previousSessions.find((session) => session.id === nextSession.id) || null;

      if (
        currentSession
        && currentSession.messages === nextSession.messages
        && currentSession.status === nextSession.status
        && currentSession.detail === nextSession.detail
        && currentSession.title === nextSession.title
        && currentSession.tag === nextSession.tag
        && currentSession.meta?.visibleContent === nextSession.meta?.visibleContent
      ) {
        return prevStore;
      }

      const nextSessions = [
        nextSession,
        ...previousSessions.filter((session) => session.id !== nextSession.id),
      ];
      const nextStore: ConversationStoreState = {
        ...prevStore,
        [employeeId]: nextSessions,
      };
      saveConversationStore(nextStore);
      return nextStore;
    });
  }, [setConversationStore]);

  const buildResourceImportMessage = useCallback(
    (flow: Record<string, any>) => {
      if (!resourceImportEmployee) {
        return null;
      }
      return createAgentMessage(resourceImportEmployee, {
        content: "",
        resourceImportFlow: flow,
      });
    },
    [createAgentMessage, resourceImportEmployee],
  );

  const resolveResourceImportFiles = useCallback((flowId: string) => {
    return resourceImportFilesRef.current.get(flowId) || [];
  }, []);

  const releaseResourceImportFiles = useCallback((flowId: string) => {
    resourceImportFilesRef.current.delete(flowId);
  }, []);

  const updateResourceImportMessage = useCallback((
    messageId: string,
    updater: (message: MessageRecord) => MessageRecord,
  ) => {
    setMessages((currentMessages) =>
      currentMessages.map((message) => (message.id === messageId ? updater(message) : message)),
    );
  }, [setMessages]);

  const handleResourceImportUploadFiles = useCallback((payload: {
    sourceMessageId: string;
    flowId: string;
    files: File[];
  }) => {
    const { sourceMessageId, flowId, files } = payload;
    if (!resourceImportEmployee || !files.length) {
      return;
    }

    resourceImportFilesRef.current.set(flowId, files);
    updateResourceImportMessage(sourceMessageId, (message) => ({
      ...message,
      resourceImportFlow: {
        ...message.resourceImportFlow,
        files: files.map((file) => ({
          name: file.name,
          size: file.size,
        })),
        status: "idle",
        error: "",
      },
    }));
  }, [resourceImportEmployee, updateResourceImportMessage]);

  const handleResourceImportStartParse = useCallback((payload: {
    messageId: string;
    flowId: string;
  }) => {
    const files = resourceImportFilesRef.current.get(payload.flowId) || [];
    if (!files.length) {
      updateResourceImportMessage(payload.messageId, (message) => ({
        ...message,
        resourceImportFlow: {
          ...message.resourceImportFlow,
          error: "请先选择至少一个文件再开始解析",
        },
      }));
      return;
    }

    const parseMessage = buildResourceImportMessage({
      flowId: payload.flowId,
      stage: "parsing",
      status: "running",
      files: files.map((file) => ({
        name: file.name,
        size: file.size,
      })),
    });

    if (!parseMessage) {
      return;
    }

    setMessages((currentMessages) => [...currentMessages, parseMessage]);
  }, [buildResourceImportMessage, setMessages, updateResourceImportMessage]);

  const handleResourceImportParseResolved = useCallback((payload: {
    messageId: string;
    flowId: string;
    preview: any;
  }) => {
    if (!resourceImportEmployee) {
      return;
    }

    updateResourceImportMessage(payload.messageId, (message) => ({
      ...message,
      resourceImportFlow: {
        ...message.resourceImportFlow,
        status: "completed",
        preview: payload.preview,
        error: "",
      },
    }));

    const structureMessage = buildResourceImportMessage({
      flowId: payload.flowId,
      stage: "structure",
      preview: payload.preview,
      resourceGroups: payload.preview.resourceGroups,
      relations: payload.preview.relations,
      locked: false,
    });

    if (!structureMessage) {
      return;
    }

    setMessages((currentMessages) => [...currentMessages, structureMessage]);
  }, [buildResourceImportMessage, resourceImportEmployee, setMessages, updateResourceImportMessage]);

  const handleResourceImportConfirmStructure = useCallback((payload: {
    messageId: string;
    flowId: string;
    preview: any;
    resourceGroups: any[];
    relations: any[];
  }) => {
    updateResourceImportMessage(payload.messageId, (message) => ({
      ...message,
      resourceImportFlow: {
        ...message.resourceImportFlow,
        preview: payload.preview,
        resourceGroups: payload.resourceGroups,
        relations: payload.relations,
        locked: true,
      },
    }));

    const confirmMessage = buildResourceImportMessage({
      flowId: payload.flowId,
      stage: "confirm",
      preview: payload.preview,
      resourceGroups: payload.resourceGroups,
      relations: payload.relations,
      locked: false,
    });

    if (!confirmMessage) {
      return;
    }

    setMessages((currentMessages) => [...currentMessages, confirmMessage]);
  }, [buildResourceImportMessage, setMessages, updateResourceImportMessage]);

  const handleResourceImportParseFailed = useCallback((payload: {
    messageId: string;
    flowId: string;
    error: string;
  }) => {
    releaseResourceImportFiles(payload.flowId);
    updateResourceImportMessage(payload.messageId, (message) => ({
      ...message,
      resourceImportFlow: {
        ...message.resourceImportFlow,
        status: "error",
        error: payload.error,
      },
    }));
  }, [releaseResourceImportFiles, updateResourceImportMessage]);

  const handleResourceImportReturnToUpload = useCallback((payload: {
    flowId: string;
    sourceMessageId?: string;
  }) => {
    releaseResourceImportFiles(payload.flowId);
    const introMessage = buildResourceImportMessage({
      flowId: createResourceImportFlowId(),
      stage: "intro",
    });

    if (!introMessage) {
      return;
    }

    setMessages((currentMessages) => [...currentMessages, introMessage]);
  }, [buildResourceImportMessage, releaseResourceImportFiles, setMessages]);

  const handleResourceImportBuildTopology = useCallback((payload: {
    messageId: string;
    flowId: string;
    preview: any;
    resourceGroups: any[];
    relations: any[];
  }) => {
    const topologyMessage = buildResourceImportMessage({
      flowId: payload.flowId,
      stage: "topology",
      preview: payload.preview,
      resourceGroups: payload.resourceGroups,
      relations: payload.relations,
      locked: false,
      readonly: false,
    });

    if (!topologyMessage) {
      return;
    }

    setMessages((currentMessages) => [
      ...currentMessages.map((message) =>
        message.id === payload.messageId
          ? {
              ...message,
              resourceImportFlow: {
                ...message.resourceImportFlow,
                resourceGroups: payload.resourceGroups,
                relations: payload.relations,
                locked: true,
              },
            }
          : message,
      ),
      topologyMessage,
    ]);
  }, [buildResourceImportMessage, setMessages]);

  const handleResourceImportBackToConfirm = useCallback((payload: {
    messageId: string;
    flowId: string;
  }) => {
    let confirmMessageId = "";

    setMessages((currentMessages) =>
      currentMessages
        .filter((message) => {
          const flow = message.resourceImportFlow;
          if (!flow || flow.flowId !== payload.flowId) {
            return true;
          }
          if (message.id === payload.messageId) {
            return false;
          }
          if (flow.stage === "importing" || flow.stage === "result") {
            return false;
          }
          return true;
        })
        .map((message) => {
          const flow = message.resourceImportFlow;
          if (flow?.flowId === payload.flowId && flow.stage === "confirm") {
            confirmMessageId = message.id;
            return {
              ...message,
              resourceImportFlow: {
                ...flow,
                locked: false,
              },
            };
          }
          return message;
        }),
    );

    window.requestAnimationFrame(() => {
      if (confirmMessageId) {
        document
          .getElementById(`message-${confirmMessageId}`)
          ?.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
  }, [setMessages]);

  const handleResourceImportSubmitImport = useCallback(async (payload: {
    messageId: string;
    flowId: string;
    preview: any;
    resourceGroups: any[];
    relations: any[];
  }) => {
    const importingMessage = buildResourceImportMessage({
      flowId: payload.flowId,
      stage: "importing",
      status: "running",
      preview: payload.preview,
      resourceGroups: payload.resourceGroups,
      relations: payload.relations,
    });

    if (!importingMessage) {
      return;
    }

    setMessages((currentMessages) => [
      ...currentMessages.map((message) =>
        message.id === payload.messageId
          ? {
              ...message,
              resourceImportFlow: {
                ...message.resourceImportFlow,
                relations: payload.relations,
                locked: true,
              },
            }
          : message,
      ),
      importingMessage,
    ]);

    try {
      const result = await submitResourceImport(
        {
          preview: payload.preview,
          resourceGroups: payload.resourceGroups,
          relations: payload.relations,
        },
        remoteAgentId || undefined,
      );

      updateResourceImportMessage(importingMessage.id, (message) => ({
        ...message,
        resourceImportFlow: {
          ...message.resourceImportFlow,
          status: "completed",
          result,
          error: "",
        },
      }));

      const resultMessage = buildResourceImportMessage({
        flowId: payload.flowId,
        stage: "result",
        preview: payload.preview,
        resourceGroups: payload.resourceGroups,
        relations: payload.relations,
        result,
      });

      if (resultMessage) {
        setMessages((currentMessages) => [...currentMessages, resultMessage]);
      }
    } catch (error) {
      const detail = error instanceof Error ? error.message : "资源导入失败";
      updateResourceImportMessage(importingMessage.id, (message) => ({
        ...message,
        resourceImportFlow: {
          ...message.resourceImportFlow,
          status: "error",
          error: detail,
        },
      }));
      updateResourceImportMessage(payload.messageId, (message) => ({
        ...message,
        resourceImportFlow: {
          ...message.resourceImportFlow,
          locked: false,
        },
      }));
    }
  }, [buildResourceImportMessage, remoteAgentId, setMessages, updateResourceImportMessage]);

  const handleResourceImportContinue = useCallback((_payload: { flowId: string }) => {
    const introMessage = buildResourceImportMessage({
      flowId: createResourceImportFlowId(),
      stage: "intro",
    });

    if (!introMessage) {
      return;
    }

    setMessages((currentMessages) => [...currentMessages, introMessage]);
  }, [buildResourceImportMessage, setMessages]);

  const findResourceImportFlowById = useCallback((flowId: string) => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const flow = messages[index]?.resourceImportFlow;
      if (flow?.flowId === flowId) {
        return flow;
      }
    }
    return null;
  }, [messages]);

  const handleResourceImportScrollToStage = useCallback((payload: {
    flowId: string;
    stage: string;
  }) => {
    const targetMessage = messages
      .slice()
      .reverse()
      .find((message) => {
        const flow = message.resourceImportFlow;
        return flow?.flowId === payload.flowId && flow.stage === payload.stage;
      });

    if (!targetMessage) {
      return;
    }

    window.requestAnimationFrame(() => {
      document
        .getElementById(`message-${targetMessage.id}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }, [messages]);

  const openResourceImport = useCallback((visibleContent = RESOURCE_IMPORT_COMMAND) => {
    if (!resourceImportEmployee) {
      return;
    }

    if (selectedEmployeeId === RESOURCE_IMPORT_OWNER_ID) {
      const flowId = createResourceImportFlowId();
      const nextMessages = [
        ...ensureObjectArray(messages),
        createUserMessage(visibleContent),
        createAgentMessage(resourceImportEmployee, {
          content: "",
          resourceImportFlow: {
            flowId,
            stage: "intro",
          },
        }),
      ];
      const nextSession = buildResourceImportSessionRecord(
        resourceImportEmployee,
        nextMessages,
        {
          visibleContent,
        },
      );
      setActivePortalResourceImportSessionId(nextSession.id);
      setCurrentChatId("");
      setMessages(nextMessages);
      upsertPortalSession(resourceImportEmployee.id, nextSession);
      return;
    }

    navigateToEmployeePage(resourceImportEmployee, {
      entry: null,
      view: "chat",
      panel: null,
      state: {
        gatewayPresentationEmployeeId: resourceImportEmployee.id,
        pendingResourceImport: {
          token: `pending-resource-import-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          targetEmployeeId: resourceImportEmployee.id,
          visibleContent,
        },
      } satisfies PortalLocationState,
    });
  }, [
    createAgentMessage,
    createUserMessage,
    messages,
    navigateToEmployeePage,
    resourceImportEmployee,
    selectedEmployeeId,
    setCurrentChatId,
    setMessages,
    upsertPortalSession,
  ]);

  const portalResourceImportSessions = useMemo(
    () =>
      ensureSessionRecords(conversationStore[resourceImportEmployee?.id || ""]).filter((session) =>
        isPortalResourceImportSession(session),
      ),
    [conversationStore, resourceImportEmployee?.id],
  );

  useEffect(() => {
    if (
      !activePortalResourceImportSessionId
      || !resourceImportEmployee
      || selectedEmployeeId !== RESOURCE_IMPORT_OWNER_ID
    ) {
      return;
    }

    const previousSession = ensureSessionRecords(conversationStore[resourceImportEmployee.id]).find(
      (session) => session.id === activePortalResourceImportSessionId,
    ) || null;
    const nextSession = buildResourceImportSessionRecord(
      resourceImportEmployee,
      messages,
      {
        sessionId: activePortalResourceImportSessionId,
        previous: previousSession,
      },
    );
    upsertPortalSession(resourceImportEmployee.id, nextSession);
  }, [
    activePortalResourceImportSessionId,
    conversationStore,
    messages,
    resourceImportEmployee,
    selectedEmployeeId,
    upsertPortalSession,
  ]);

  return {
    resourceImportEmployee,
    activePortalResourceImportSessionId,
    setActivePortalResourceImportSessionId,
    portalResourceImportSessions,
    resolveResourceImportFiles,
    releaseResourceImportFiles,
    handleResourceImportUploadFiles,
    handleResourceImportStartParse,
    handleResourceImportParseResolved,
    handleResourceImportConfirmStructure,
    handleResourceImportParseFailed,
    handleResourceImportReturnToUpload,
    handleResourceImportBuildTopology,
    handleResourceImportBackToConfirm,
    handleResourceImportSubmitImport,
    handleResourceImportContinue,
    findResourceImportFlowById,
    handleResourceImportScrollToStage,
    openResourceImport,
  };
}
