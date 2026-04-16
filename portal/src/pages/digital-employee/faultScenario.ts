import { diagnoseFaultScenario } from "../../api/faultScenario";
import { createAgentMessage, createUserMessage } from "./helpers";

const CMDB_KEYWORD_RE = /cmdb/i;
const DATABASE_FAULT_KEYWORD_RE = /(mysql|死锁)/i;
const CMDB_WRITE_ACTION_RE = /(新增|插入)/i;
const FAILURE_HINT_RE = /(失败|报错|超时)/i;

export const FAULT_SCENARIO_ANALYZING_PLACEHOLDER = "正在关联分析...";

type FaultScenarioMessage = {
  id: string;
  content?: string;
  [key: string]: unknown;
};

type SetFaultScenarioMessages = (
  value:
    | FaultScenarioMessage[]
    | ((prevMessages: FaultScenarioMessage[]) => FaultScenarioMessage[]),
) => void;

type FaultScenarioDiagnosisResult = {
  summary?: string;
  [key: string]: unknown;
};

type FaultScenarioDiagnosisResponse = {
  result?: FaultScenarioDiagnosisResult;
};

interface MaybeHandleFaultScenarioMessageParams {
  currentEmployee: { id?: string } | null | undefined;
  content: string;
  visibleContent?: string;
  sessionId?: string;
  signal?: AbortSignal;
  setActiveAssistantMessageId?: (messageId: string | null) => void;
  setMessages: SetFaultScenarioMessages;
}

function isTargetFaultScenario(content: string) {
  const normalized = String(content || "");
  return (
    (CMDB_KEYWORD_RE.test(normalized)
      && CMDB_WRITE_ACTION_RE.test(normalized)
      && FAILURE_HINT_RE.test(normalized))
    || (DATABASE_FAULT_KEYWORD_RE.test(normalized)
      && (CMDB_KEYWORD_RE.test(normalized) || CMDB_WRITE_ACTION_RE.test(normalized)))
  );
}

export async function maybeHandleFaultScenarioMessage({
  currentEmployee,
  content,
  visibleContent,
  sessionId,
  signal,
  setActiveAssistantMessageId,
  setMessages,
}: MaybeHandleFaultScenarioMessageParams) {
  if (currentEmployee?.id !== "fault" || !isTargetFaultScenario(content || "")) {
    return { handled: false, succeeded: false };
  }

  const agentMessageId = `fault-scenario-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  setActiveAssistantMessageId?.(agentMessageId);

  setMessages((prevMessages) => [
    ...prevMessages,
    createUserMessage(visibleContent || content),
    createAgentMessage(currentEmployee, {
      id: agentMessageId,
      content: FAULT_SCENARIO_ANALYZING_PLACEHOLDER,
    }),
  ]);

  try {
    const result = await diagnoseFaultScenario({
      sessionId: sessionId || `fault-scenario-${Date.now()}`,
      employeeId: "fault",
      content,
    }, { signal }) as FaultScenarioDiagnosisResponse;

    setMessages((prevMessages) =>
      prevMessages.map((item) =>
        item.id === agentMessageId
          ? {
              ...item,
              content: result?.result?.summary || "已完成关联分析。",
              faultScenarioResult: result?.result,
            }
          : item,
      ),
    );

    return { handled: true, succeeded: true };
  } catch (error: any) {
    if (error?.name === "AbortError") {
      return { handled: true, succeeded: false };
    }

    setMessages((prevMessages) =>
      prevMessages.map((item) =>
        item.id === agentMessageId
          ? {
              ...item,
              content: `关联分析失败：${String(error?.message || "请稍后重试")}`,
            }
          : item,
      ),
    );

    return { handled: true, succeeded: false };
  } finally {
    setActiveAssistantMessageId?.(null);
  }
}
