import { message } from "antd";
import { useState } from "react";

import type { ManualOperationGuide } from "../fault-scenario/shared";
import { PortalQwenPawMarkdown } from "./PortalQwenPawMarkdown";

export function ManualOperationGuidePanel({ guide }: { guide: ManualOperationGuide }) {
  const [copying, setCopying] = useState(false);
  const copyGuide = async () => {
    if (!navigator.clipboard) {
      message.error("当前环境不支持复制，请选择指南文本复制。");
      return;
    }
    setCopying(true);
    try {
      await navigator.clipboard.writeText(guide.markdown);
      message.success("已复制完整人工操作指南");
    } catch {
      message.error("复制失败，请选择指南文本复制。");
    } finally {
      setCopying(false);
    }
  };

  return (
    <section className="manual-operation-guide" aria-label="人工操作指南">
      <div className="manual-operation-guide-header">
        <div>
          <h4>按部署环境处置</h4>
          <p>仅依据 CMDB，供运维人工执行。系统未登录或执行以下命令。</p>
        </div>
        <button type="button" onClick={copyGuide} disabled={copying}>
          {copying ? "正在复制…" : "复制完整指南"}
        </button>
      </div>
      <PortalQwenPawMarkdown content={guide.markdown} isStreaming={false} />
    </section>
  );
}
