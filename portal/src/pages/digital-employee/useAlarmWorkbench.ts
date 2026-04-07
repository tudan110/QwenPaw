import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { listAlarmWorkorders } from "../../api/portalWorkorders";
import { getFaultDisposalRecoveryVisualization } from "../../api/faultDisposal";
import {
  ALARM_WORKORDER_LIMIT,
  buildFaultWorkbenchChatMeta,
  buildFaultWorkbenchChatName,
  buildFaultWorkbenchDiagnosePrompt,
  buildFaultWorkbenchExecutePrompt,
  buildFaultWorkbenchVisiblePrompt,
  createAlarmWorkorderMessage,
  createAgentMessage,
  createRemoteSessionId,
  createUserMessage,
  normalizeDisposalOperationPayload,
  selectAlarmWorkbenchVisibleWorkorders,
} from "./helpers";

export function useAlarmWorkbench({
  currentEmployee,
  isAlarmWorkbenchMode,
  currentSessionId,
  handleRemoteSendMessage,
  messages,
  setMessages,
}: {
  currentEmployee: any;
  isAlarmWorkbenchMode: boolean;
  currentSessionId: string;
  handleRemoteSendMessage: (
    content: string,
    options?: {
      visibleContent?: string;
      chatName?: string;
      chatMeta?: any;
      forceNewChat?: boolean;
      sessionId?: string;
    },
  ) => Promise<boolean>;
  messages: any[];
  setMessages: Dispatch<SetStateAction<any[]>>;
}) {
  const [alarmWorkorders, setAlarmWorkorders] = useState<any[]>([]);
  const [alarmWorkordersLoading, setAlarmWorkordersLoading] = useState(false);
  const [alarmWorkordersError, setAlarmWorkordersError] = useState("");
  const [ticketActionNotice, setTicketActionNotice] = useState("");
  const [faultDiagnosisBusy, setFaultDiagnosisBusy] = useState(false);
  const [pendingDisposalAction, setPendingDisposalAction] = useState<any>(null);
  const [isSubmittingDisposalAction, setIsSubmittingDisposalAction] = useState(false);
  const ticketNoticeTimerRef = useRef(0);
  const currentEmployeeRef = useRef(currentEmployee);
  const isAlarmWorkbenchModeRef = useRef(isAlarmWorkbenchMode);
  const messagesRef = useRef(messages);
  const alarmWorkordersRef = useRef<any[]>([]);
  const currentSessionIdRef = useRef(currentSessionId);

  useEffect(() => {
    currentEmployeeRef.current = currentEmployee;
  }, [currentEmployee]);

  useEffect(() => {
    isAlarmWorkbenchModeRef.current = isAlarmWorkbenchMode;
  }, [isAlarmWorkbenchMode]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    alarmWorkordersRef.current = alarmWorkorders;
  }, [alarmWorkorders]);

  useEffect(() => {
    currentSessionIdRef.current = currentSessionId;
  }, [currentSessionId]);

  useEffect(
    () => () => {
      if (ticketNoticeTimerRef.current) {
        window.clearTimeout(ticketNoticeTimerRef.current);
      }
    },
    [],
  );

  const resetAlarmWorkbench = useCallback(() => {
    setAlarmWorkorders([]);
    setAlarmWorkordersError("");
    setFaultDiagnosisBusy(false);
    setPendingDisposalAction(null);
    setIsSubmittingDisposalAction(false);
    if (ticketNoticeTimerRef.current) {
      window.clearTimeout(ticketNoticeTimerRef.current);
      ticketNoticeTimerRef.current = 0;
    }
    setTicketActionNotice("");
  }, []);

  const loadAlarmWorkorders = useCallback(async () => {
    const employee = currentEmployeeRef.current;
    if (!isAlarmWorkbenchModeRef.current || !employee) {
      return;
    }

    setAlarmWorkordersLoading(true);
    setAlarmWorkordersError("");
    setMessages([
      createAlarmWorkorderMessage(employee, {
        content: "告警已触发，我正在为您查询待处置工单...",
        workorders: [],
        workordersLoading: true,
        workordersError: "",
      }),
    ]);

    try {
      const response = await listAlarmWorkorders({
        limit: ALARM_WORKORDER_LIMIT,
      });
      const items = Array.isArray(response)
        ? response
        : Array.isArray((response as any)?.items)
          ? (response as any).items
          : [];
      const visibleItems = selectAlarmWorkbenchVisibleWorkorders(items);
      setAlarmWorkorders(items);
      setMessages([
        createAlarmWorkorderMessage(employee, {
          content: visibleItems.length
            ? `检测到告警触发，已为您接管当前可处置入口工单。您可以先从“${visibleItems[0].title}”开始处置。`
            : "告警已触发，但当前没有查询到待处置工单。您也可以继续告诉我需要排查的故障。",
          workorders: visibleItems,
          workordersLoading: false,
          workordersError: "",
        }),
      ]);
    } catch (error: any) {
      setAlarmWorkorders([]);
      const errorMessage = String(error?.message || "告警工单查询失败")
        .replace(/^\{"detail":"([\s\S]*)"\}$/i, "$1")
        .trim();
      setAlarmWorkordersError(errorMessage);
      setMessages([
        createAlarmWorkorderMessage(employee, {
          content: "告警已触发，但工单查询失败。您可以稍后刷新，或直接告诉我需要优先处置的故障。",
          workorders: [],
          workordersLoading: false,
          workordersError: errorMessage,
        }),
      ]);
    } finally {
      setAlarmWorkordersLoading(false);
    }
  }, [setMessages]);

  useEffect(() => {
    if (!isAlarmWorkbenchMode) {
      return;
    }
    void loadAlarmWorkorders();
  }, [currentEmployee?.id, isAlarmWorkbenchMode, loadAlarmWorkorders]);

  function showTicketActionToast(message: string) {
    setTicketActionNotice(message);
    if (ticketNoticeTimerRef.current) {
      window.clearTimeout(ticketNoticeTimerRef.current);
    }
    ticketNoticeTimerRef.current = window.setTimeout(() => {
      setTicketActionNotice("");
      ticketNoticeTimerRef.current = 0;
    }, 2400) as unknown as number;
  }

  function updateAlarmWorkbenchMessage(messageId: string, updater: (message: any) => any) {
    setMessages((prevMessages) =>
      prevMessages.map((message) =>
        message.id === messageId ? updater(message) : message,
      ),
    );
  }

  async function appendRecoveryVisualizationPreview(operation: any) {
    const employee = currentEmployeeRef.current;
    if (!employee) {
      return null;
    }

    const response = await getFaultDisposalRecoveryVisualization(operation);
    const visualization = response?.visualization;
    if (!visualization) {
      return null;
    }

    const messageId = `recovery-visualization-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const content = [
      "**恢复趋势实时采集**",
      "",
      "> 已开始采集处置后指标，图表会按实时采样节奏持续追加。",
      "",
      "```portal-visualization",
      JSON.stringify(visualization),
      "```",
    ].join("\n");

    setMessages((prevMessages) => [
      ...prevMessages,
      createAgentMessage(employee, {
        id: messageId,
        content,
        processBlocks: [],
      }),
    ]);
    return messageId;
  }

  async function runAlarmWorkbenchDiagnosis(workorder: any) {
    const employee = currentEmployeeRef.current;
    if (!employee) {
      return;
    }

    if (
      messagesRef.current.some(
        (message) =>
          message.type === "user" &&
          message.content === buildFaultWorkbenchVisiblePrompt(workorder),
      )
    ) {
      showTicketActionToast(`工单 ${workorder.workorderNo} 已进入处置流程`);
      return;
    }

    setFaultDiagnosisBusy(true);

    try {
      const sessionId = createRemoteSessionId(employee.id);
      const visibleContent = buildFaultWorkbenchVisiblePrompt(workorder);
      const succeeded = await handleRemoteSendMessage(
        buildFaultWorkbenchDiagnosePrompt(workorder, alarmWorkordersRef.current),
        {
          visibleContent,
          chatName: buildFaultWorkbenchChatName(workorder),
          chatMeta: buildFaultWorkbenchChatMeta(workorder),
          forceNewChat: true,
          sessionId,
        },
      );

      if (!succeeded) {
        showTicketActionToast("故障处置分析未成功完成，请查看会话输出");
      }
    } catch (error: any) {
      const errorMessage = error.message || "故障处置分析失败";
      showTicketActionToast(errorMessage);
    } finally {
      setFaultDiagnosisBusy(false);
    }
  }

  function handleAlarmDisposalOperationRequest(messageId: string, operation: any) {
    const normalizedOperation = normalizeDisposalOperationPayload(operation);
    if (!normalizedOperation) {
      showTicketActionToast("未找到可执行的处置动作");
      return;
    }

    if (normalizedOperation.status === "success") {
      showTicketActionToast("处置动作已执行");
      return;
    }

    setPendingDisposalAction({
      messageId,
      operation: normalizedOperation,
    });
  }

  function handleCancelDisposalAction() {
    if (isSubmittingDisposalAction) {
      return;
    }
    setPendingDisposalAction(null);
  }

  async function handleConfirmDisposalAction() {
    if (!pendingDisposalAction) {
      return;
    }

    const { messageId, operation } = pendingDisposalAction;
    setIsSubmittingDisposalAction(true);
    updateAlarmWorkbenchMessage(messageId, (message) => ({
      ...message,
      disposalOperation: {
        ...(message.disposalOperation || operation),
        status: "running",
      },
    }));
    setPendingDisposalAction(null);

    const visibleContent = `执行建议动作：${operation.title || "故障处置动作"}`;

    try {
      const activeSessionId = currentSessionIdRef.current;
      if (!activeSessionId) {
        throw new Error("未找到当前会话，请重新发起故障处置");
      }

      const sourceWorkorders = alarmWorkordersRef.current;
      const sourceWorkorder = sourceWorkorders.find(
        (item) => item?.workorderNo === operation.sourceWorkorderNo,
      );
      if (!sourceWorkorder) {
        throw new Error("未找到动作对应的来源工单上下文");
      }

      const succeeded = await handleRemoteSendMessage(
        buildFaultWorkbenchExecutePrompt(sourceWorkorder, sourceWorkorders, operation),
        {
          visibleContent,
          sessionId: activeSessionId,
        },
      );

      if (!succeeded) {
        throw new Error("处置动作执行未成功完成，请查看会话输出");
      }

      await appendRecoveryVisualizationPreview(operation);

      updateAlarmWorkbenchMessage(messageId, (message) => ({
        ...message,
        disposalOperation: {
          ...(message.disposalOperation || operation),
          status: "success",
        },
        hideDisposalOperation: true,
      }));
      showTicketActionToast("处置指令已提交");
    } catch (error: any) {
      updateAlarmWorkbenchMessage(messageId, (message) => ({
        ...message,
        disposalOperation: {
          ...(message.disposalOperation || operation),
          status: "ready",
        },
        hideDisposalOperation: false,
      }));
      showTicketActionToast(error.message || "处置动作执行失败");
    } finally {
      setIsSubmittingDisposalAction(false);
    }
  }

  function handleAlarmWorkbenchTicketAction(actionLabel: string, workorder: any) {
    if (actionLabel !== "去处置") {
      showTicketActionToast(`${actionLabel}流程待接入：${workorder.workorderNo}`);
      return;
    }

    if (faultDiagnosisBusy) {
      showTicketActionToast("故障处置分析正在执行，请稍候");
      return;
    }

    if (isAlarmWorkbenchMode) {
      void runAlarmWorkbenchDiagnosis(workorder);
      return;
    }

    showTicketActionToast(`${actionLabel}流程待接入：${workorder.workorderNo}`);
  }

  return {
    alarmWorkorders,
    alarmWorkordersLoading,
    alarmWorkordersError,
    ticketActionNotice,
    faultDiagnosisBusy,
    pendingDisposalAction,
    isSubmittingDisposalAction,
    loadAlarmWorkorders,
    handleAlarmWorkbenchTicketAction,
    handleAlarmDisposalOperationRequest,
    handleCancelDisposalAction,
    handleConfirmDisposalAction,
    resetAlarmWorkbench,
  };
}
