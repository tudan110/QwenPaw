import { useCallback, useEffect, useRef, useState } from "react";
import { getChatUserId } from "../../auth/ssoSession";
import {
  isMissingApprovalRequest,
  listMainChatApprovals,
  resolveMainChatApproval,
} from "../../api/mainChatApproval";
import {
  approvalRemainingSeconds,
  approvalStorageKey,
  normalizeApprovalLevel,
  selectMainChatApprovals,
  type MainChatApproval,
  type MainChatApprovalLevel,
} from "./mainChatApproval";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "审批请求失败，请重试。";
}

export function useMainChatApprovalMode(agentId: string | null, sessionId: string) {
  const userId = getChatUserId();
  const key = approvalStorageKey(userId, agentId || "", sessionId);
  const [selection, setSelection] = useState<{ key: string; level: MainChatApprovalLevel } | null>(null);
  const [storageError, setStorageError] = useState("");
  let savedLevel: MainChatApprovalLevel = null;
  if (sessionId && selection?.key !== key) {
    try {
      savedLevel = normalizeApprovalLevel(window.localStorage.getItem(key));
    } catch (error) {
      console.warn("Unable to read main chat approval mode", error);
    }
  }
  const level = selection?.key === key ? selection.level : savedLevel;

  const rememberForSession = useCallback((nextSessionId: string, nextLevel: MainChatApprovalLevel) => {
    const nextKey = approvalStorageKey(userId, agentId || "", nextSessionId);
    setSelection({ key: nextKey, level: nextLevel });
    setStorageError("");
    if (!nextSessionId) return;
    try {
      if (nextLevel === null) {
        window.localStorage.removeItem(nextKey);
      } else {
        window.localStorage.setItem(nextKey, nextLevel);
      }
    } catch (error) {
      console.warn("Unable to save main chat approval mode", error);
      setStorageError("模式已应用，但无法保存到浏览器；刷新后需重新选择。");
    }
  }, [agentId, userId]);

  return {
    level,
    storageError: selection?.key === key ? storageError : "",
    rememberForSession,
    setLevel: (nextLevel: MainChatApprovalLevel) => rememberForSession(sessionId, nextLevel),
  };
}

type ApprovalAction = "exact" | "similar" | "deny" | "cancel";
interface ApprovalState {
  key: string;
  items: MainChatApproval[];
  pollError: string;
  actionError: string;
  notice: string;
  busy: Record<string, ApprovalAction>;
}

export function useMainChatApprovals({
  agentId,
  sessionId,
  enabled,
  onCancelTask,
}: {
  agentId: string | null;
  sessionId: string;
  enabled: boolean;
  onCancelTask: (signal: AbortSignal) => Promise<void>;
}) {
  const key = approvalStorageKey(getChatUserId(), agentId || "", sessionId);
  const [state, setState] = useState<ApprovalState>({
    key: "", items: [], pollError: "", actionError: "", notice: "", busy: {},
  });
  const [refresh, setRefresh] = useState(0);
  const contextRef = useRef({ key, enabled });
  contextRef.current = { key, enabled };
  const handledRef = useRef({ key, ids: new Set<string>() });
  if (handledRef.current.key !== key) {
    handledRef.current = { key, ids: new Set<string>() };
  }
  const actionControllers = useRef(new Set<AbortController>());
  const inFlightRef = useRef(new Set<string>());
  const revisionRef = useRef(0);

  useEffect(() => {
    const controllers = actionControllers.current;
    return () => {
      controllers.forEach((controller) => controller.abort());
      controllers.clear();
      inFlightRef.current.clear();
    };
  }, [key, enabled]);

  useEffect(() => {
    if (!enabled || !agentId || !sessionId) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    let controller: AbortController;
    const tick = async () => {
      controller = new AbortController();
      const revision = revisionRef.current;
      const timeout = window.setTimeout(() => controller.abort(), 15000);
      try {
        const response = await listMainChatApprovals(agentId, sessionId, controller.signal);
        if (disposed || revision !== revisionRef.current) return;
        setState((previous) => {
          if (contextRef.current.key !== key || !contextRef.current.enabled
            || revision !== revisionRef.current) return previous;
          const items = selectMainChatApprovals(response, agentId, sessionId)
            .filter((item) => !handledRef.current.ids.has(item.request_id));
          if (previous.key === key && !previous.pollError
            && JSON.stringify(previous.items) === JSON.stringify(items)) return previous;
          return {
            key,
            items,
            pollError: "",
            actionError: previous.key === key ? previous.actionError : "",
            notice: previous.key === key ? previous.notice : "",
            busy: previous.key === key ? previous.busy : {},
          };
        });
      } catch (error) {
        if (disposed || revision !== revisionRef.current) return;
        setState((previous) => ({
          key,
          items: previous.key === key ? previous.items : [],
          busy: previous.key === key ? previous.busy : {},
          actionError: previous.key === key ? previous.actionError : "",
          notice: previous.key === key ? previous.notice : "",
          pollError: controller.signal.aborted
            ? "审批列表请求超时，正在重试。"
            : `无法获取审批请求：${errorMessage(error)}`,
        }));
      } finally {
        window.clearTimeout(timeout);
        if (!disposed) timer = setTimeout(tick, 2500);
      }
    };
    void tick();
    return () => {
      disposed = true;
      controller?.abort();
      clearTimeout(timer);
    };
  }, [agentId, enabled, key, sessionId, refresh]);

  const act = async (approval: MainChatApproval, action: ApprovalAction) => {
    if (!enabled || !agentId || !contextRef.current.enabled || contextRef.current.key !== key) return;
    if (!selectMainChatApprovals([approval], agentId, sessionId).length) return;
    const actionKey = `${key}:${approval.request_id}`;
    if (inFlightRef.current.has(actionKey)) return;
    if (action !== "cancel" && approvalRemainingSeconds(approval) <= 0) {
      setState((previous) => ({ ...previous, actionError: "审批已超时，无法继续批准或拒绝。" }));
      return;
    }
    const controller = new AbortController();
    revisionRef.current += 1;
    inFlightRef.current.add(actionKey);
    actionControllers.current.add(controller);
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    setState((previous) => ({
      ...previous,
      key,
      actionError: "",
      notice: "",
      busy: { ...previous.busy, [approval.request_id]: action },
    }));
    try {
      if (action === "cancel") {
        await onCancelTask(controller.signal);
      } else {
        await resolveMainChatApproval(
          agentId,
          sessionId,
          approval.request_id,
          action === "deny" ? "deny" : "approve",
          controller.signal,
          action === "similar" ? "similar" : "exact",
        );
      }
      if (contextRef.current.key !== key || !contextRef.current.enabled) return;
      revisionRef.current += 1;
      if (action === "cancel") {
        state.items.forEach((item) => handledRef.current.ids.add(item.request_id));
      }
      handledRef.current.ids.add(approval.request_id);
      setState((previous) => ({
        ...previous,
        items: action === "cancel" ? [] : previous.items.filter((item) => item.request_id !== approval.request_id),
      }));
      setRefresh((value) => value + 1);
    } catch (error) {
      if (contextRef.current.key !== key || !contextRef.current.enabled) return;
      if (action !== "cancel" && isMissingApprovalRequest(error)) {
        handledRef.current.ids.add(approval.request_id);
        revisionRef.current += 1;
        setState((previous) => ({
          ...previous,
          items: previous.items.filter((item) => item.request_id !== approval.request_id),
          actionError: "",
          notice: "该审批已失效，可能已处理、任务已取消或后端已重启。本次操作未获确认，请重新发起任务。",
        }));
        setRefresh((value) => value + 1);
        return;
      }
      setState((previous) => ({
        ...previous,
        actionError: controller.signal.aborted ? "审批操作超时，请刷新状态后确认结果。" : errorMessage(error),
      }));
    } finally {
      window.clearTimeout(timeout);
      actionControllers.current.delete(controller);
      inFlightRef.current.delete(actionKey);
      if (contextRef.current.key === key) {
        setState((previous) => {
          const busy = { ...previous.busy };
          delete busy[approval.request_id];
          return { ...previous, busy };
        });
      }
    }
  };

  const visible = enabled && state.key === key;
  return {
    items: visible ? state.items : [],
    error: visible ? state.actionError || state.pollError : "",
    notice: visible ? state.notice : "",
    busy: visible ? state.busy : {},
    act,
    retry: () => {
      setState((previous) => ({ ...previous, actionError: "" }));
      setRefresh((value) => value + 1);
    },
  };
}
