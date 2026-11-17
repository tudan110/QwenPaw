import { useCallback, useRef, useState } from "react";
import { Alert } from "antd";
import { useTranslation } from "react-i18next";
import { chatApi } from "../../api/modules/chat";

type Feedback = {
  id: number;
  scope: string;
  status: "requesting" | "accepted" | "notRunning" | "failed";
  at: string;
};

export function useStopFeedback(scope: string) {
  const { t } = useTranslation();
  const [feedback, setFeedback] = useState<Feedback>();
  const sequence = useRef(0);
  const requestStop = useCallback(
    async (chatId: string) => {
      const at = new Date().toLocaleString();
      const id = ++sequence.current;
      setFeedback({ id, scope, status: "requesting", at });
      try {
        const result = await chatApi.stopChat(chatId);
        if (id === sequence.current)
          setFeedback({
            id,
            scope,
            status: result.stopped ? "accepted" : "notRunning",
            at,
          });
        return result;
      } catch (error) {
        if (id === sequence.current)
          setFeedback({ id, scope, status: "failed", at });
        throw error;
      }
    },
    [scope],
  );

  const notice =
    feedback?.scope === scope ? (
      <Alert
        key={feedback.id}
        showIcon
        closable
        onClose={() => setFeedback(undefined)}
        type={feedback.status === "failed" ? "error" : "info"}
        message={`${t(`trustedEvidence.stop.${feedback.status}`)} · ${
          feedback.at
        }`}
        description={t(
          "trustedEvidence.stopBoundary",
          "This reports the local cancellation request. Remote tools and external operations may still be running; no remote stop or rollback has been confirmed.",
        )}
        style={{ margin: "8px 16px" }}
      />
    ) : null;
  return { requestStop, notice };
}
