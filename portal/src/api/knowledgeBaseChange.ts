export const KNOWLEDGE_BASE_CHANGE_EVENT = "portal:knowledge-base-changed";
export const KNOWLEDGE_BASE_CHANGE_CHANNEL = "portal-knowledge-base-changes";
export const KNOWLEDGE_BASE_CHANGE_STORAGE_KEY = "portal:knowledge-base:last-change";

export type KnowledgeBaseChangeDetail = {
  id: string;
  sourceId: string;
  reason: string;
  timestamp: number;
};

export function createKnowledgeBaseChangeId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function emitKnowledgeBaseChanged(sourceId: string, reason: string) {
  if (typeof window === "undefined") {
    return;
  }
  const detail: KnowledgeBaseChangeDetail = {
    id: createKnowledgeBaseChangeId(),
    sourceId,
    reason,
    timestamp: Date.now(),
  };
  window.dispatchEvent(new CustomEvent<KnowledgeBaseChangeDetail>(
    KNOWLEDGE_BASE_CHANGE_EVENT,
    { detail },
  ));
  try {
    const channel = new BroadcastChannel(KNOWLEDGE_BASE_CHANGE_CHANNEL);
    channel.postMessage(detail);
    channel.close();
  } catch {
    // BroadcastChannel is not available in every embedded browser surface.
  }
  try {
    window.localStorage.setItem(KNOWLEDGE_BASE_CHANGE_STORAGE_KEY, JSON.stringify(detail));
  } catch {
    // Storage may be blocked in private or sandboxed iframe contexts.
  }
}
