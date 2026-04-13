import { memo } from "react";
import { Markdown } from "@agentscope-ai/chat";

type PortalQwenPawMarkdownProps = {
  className?: string;
  content: string;
  isStreaming?: boolean;
};

export const PortalQwenPawMarkdown = memo(function PortalQwenPawMarkdown({
  className,
  content,
  isStreaming = false,
}: PortalQwenPawMarkdownProps) {
  return (
    <div className={["portal-qwenpaw-markdown-host", className].filter(Boolean).join(" ")}>
      <Markdown
        content={content}
        cursor={isStreaming}
        baseFontSize={14}
        baseLineHeight={1.7}
        disableImage={false}
        allowHtml={false}
        animation={false}
      />
    </div>
  );
});
