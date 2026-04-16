import { memo, useEffect, useRef, useState } from "react";
import { employeeStepDescriptions } from "../../data/portalData";
import { EChartsBlock } from "../../components/EChartsBlock";
import { PortalVisualizationBlock } from "../../components/PortalVisualizationBlock";
import { PortalQwenPawMarkdown } from "../../components/PortalQwenPawMarkdown";
import {
  extractVisualBlocks,
  extractPortalActionPayload,
  getSeverityClassName,
  normalizeMarkdownDisplayContent,
} from "./helpers";
import { FaultScenarioResultCard } from "./faultScenarioComponents";

export function AlarmWorkorderBoard({
  workorders,
  loading,
  error,
  notice,
  onRefresh,
  onAction,
  inline = false,
}: any) {
  return (
    <div className={inline ? "alarm-workorder-board inline" : "alarm-workorder-board"}>
      <div className="alarm-workorder-toolbar">
        <div className="alarm-workorder-toolbar-text">
          <h3>以下是需要处置的告警工单</h3>
          <p>告警已触发故障处置员，当前先展示待处置工单，后续可在此接入不同类型故障的处置流程。</p>
        </div>
        <button className="alarm-workorder-refresh" onClick={onRefresh} disabled={loading}>
          <i className={`fas ${loading ? "fa-spinner fa-spin" : "fa-rotate-right"}`} />
          刷新
        </button>
      </div>

      {notice ? <div className="alarm-workorder-notice">{notice}</div> : null}

      {loading ? (
        <div className="alarm-workorder-empty">
          <i className="fas fa-spinner fa-spin" />
          <p>正在查询 real-alarm 告警数据...</p>
        </div>
      ) : error ? (
        <div className="alarm-workorder-empty error">
          <i className="fas fa-triangle-exclamation" />
          <p>{error}</p>
        </div>
      ) : workorders.length ? (
        <div className="alarm-workorder-list">
          {workorders.map((workorder: any) => (
            <AlarmWorkorderCard
              key={workorder.id}
              onAction={onAction}
              workorder={workorder}
            />
          ))}
        </div>
      ) : (
        <div className="alarm-workorder-empty">
          <i className="fas fa-inbox" />
          <p>当前没有查询到待处置告警工单。</p>
        </div>
      )}
    </div>
  );
}

function AlarmWorkorderCard({ workorder, onAction }: any) {
  const severityClass = getSeverityClassName(workorder.severityLevel);
  const actionButtons = ["去处置", "转派", "升级", "回单"];

  return (
    <div className={`alarm-workorder-card ${severityClass}`}>
      <div className="alarm-workorder-card-header">
        <div className="alarm-workorder-title-group">
          <span className={`alarm-workorder-severity-dot ${severityClass}`} />
          <div>
            <h4>{`${workorder.severity} | ${workorder.title}`}</h4>
            <p>故障处置员（告警驱动工单）</p>
          </div>
        </div>
        <span className="alarm-workorder-status">{workorder.status}</span>
      </div>

      <div className="alarm-workorder-meta-grid">
        <div>
          <span>工单号</span>
          <strong>{workorder.workorderNo}</strong>
        </div>
        <div>
          <span>创建时间</span>
          <strong>{workorder.eventTime}</strong>
        </div>
        <div>
          <span>设备 IP</span>
          <strong>{workorder.manageIp}</strong>
        </div>
        <div>
          <span>设备名称</span>
          <strong>{workorder.deviceName}</strong>
        </div>
      </div>

      <div className="alarm-workorder-description">
        <div className="alarm-workorder-description-label">故障描述</div>
        <p>{workorder.description}</p>
      </div>

      <div className="alarm-workorder-tags">
        <span>{workorder.severity}</span>
        <span>{workorder.status}</span>
        <span>{`定位对象：${workorder.locateName}`}</span>
        <span>{`专业：${workorder.speciality}`}</span>
        <span>{`区域：${workorder.region}`}</span>
        <span>{`告警次数：${workorder.actionCount}`}</span>
      </div>

      <div className="alarm-workorder-actions">
        {actionButtons.map((label, index) => (
          <button
            key={label}
            className={index === 0 ? "alarm-workorder-action primary" : "alarm-workorder-action"}
            onClick={() => onAction(label, workorder)}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function DisposalOperationCard({ action, onExecute }: any) {
  if (!action) {
    return null;
  }

  const statusText =
    action.status === "success"
      ? "已执行"
      : action.status === "running"
      ? "执行中"
      : "待确认";

  return (
    <div className="disposal-operation-card">
      <div className="disposal-operation-header">
        <div>
          <h4>{action.title}</h4>
          <p>{action.summary}</p>
        </div>
        <span className={`disposal-operation-status ${action.status || "ready"}`}>
          {statusText}
        </span>
      </div>
      <div className="disposal-operation-meta">
        <div>
          <span>根因工单</span>
          <strong>{action.rootCauseWorkorderNo}</strong>
        </div>
        <div>
          <span>SQL_ID</span>
          <strong>{action.sqlId}</strong>
        </div>
        <div>
          <span>会话ID</span>
          <strong>{action.sessionId}</strong>
        </div>
        <div>
          <span>实例</span>
          <strong>{action.locateName}</strong>
        </div>
        <div>
          <span>处置对象</span>
          <strong>{action.targetSummary || "数据库核心业务慢 SQL 会话"}</strong>
        </div>
      </div>
      <div className="disposal-operation-actions">
        <button
          className="alarm-workorder-action primary"
          disabled={action.status === "running" || action.status === "success"}
          onClick={onExecute}
        >
          <i
            className={`fas ${
              action.status === "running" ? "fa-spinner fa-spin" : "fa-bolt"
            }`}
          />{" "}
          {action.status === "success" ? "慢SQL已终止" : "杀掉慢SQL"}
        </button>
      </div>
    </div>
  );
}

export const ChatMessageItem = memo(function ChatMessageItem({
  currentEmployee,
  isStreamingMessage,
  message,
  onDisposalAction,
  pageTheme,
  onTicketAction,
  onTicketRefresh,
  ticketActionNotice,
}: any) {
  const allBlocks = message.processBlocks || [];
  const hasInterleavedResponses = allBlocks.some(
    (block: any) => block?.kind === "response" && block.content,
  );

  // Interleaved mode: response blocks exist in processBlocks (loaded history)
  // Legacy mode: no response blocks, text lives in message.content (streaming)
  const displayBlocks = hasInterleavedResponses
    ? allBlocks
    : allBlocks.filter((block: any) => block?.kind !== "response");

  const renderedMessageContent = hasInterleavedResponses
    ? (isStreamingMessage ? message.content : null)
    : (message.content || [...allBlocks].reverse().find(
        (block: any) => block?.kind === "response" && block.content,
      )?.content || "");

  // For copy button: collect all response text from interleaved blocks or use renderedMessageContent
  const copyableContent = hasInterleavedResponses
    ? allBlocks
        .filter((block: any) => block?.kind === "response" && block.content)
        .map((block: any) => block.content)
        .join("\n\n")
    : renderedMessageContent;

  const hasWorkorders =
    Boolean(message.workorders?.length) ||
    Boolean(message.workordersLoading) ||
    Boolean(message.workordersError);
  const effectiveDisposalOperation =
    message.disposalOperation ||
    extractPortalActionPayload(renderedMessageContent || message.content || "");
  const shouldShowDisposalOperation =
    Boolean(effectiveDisposalOperation) &&
    effectiveDisposalOperation.status !== "success" &&
    !message.hideDisposalOperation;
  const faultScenarioResult = message.faultScenarioResult;

  return (
    <div className={message.type === "user" ? "message user" : "message agent"}>
      <div
        className="message-avatar"
        style={message.type === "agent" ? { background: message.gradient } : {}}
      >
        <i className={`fas ${message.type === "user" ? "fa-user" : message.icon}`} />
      </div>
      <div className="message-content">
        {displayBlocks.length ? (
          <div className="process-trace">
            {displayBlocks.map((block: any) =>
              block.kind === "response" ? (
                <div
                  key={block.id}
                  className="message-bubble markdown-bubble interleaved-response-bubble"
                >
                  <MessageMarkdown content={block.content} />
                </div>
              ) : (
                <details
                  key={block.id}
                  className={`trace-block ${block.kind}`}
                  open={block.defaultOpen}
                >
                  <summary className="trace-summary">
                    <span className="trace-label">
                      <i className={`fas ${block.icon}`} />
                      {block.title}
                    </span>
                    {block.subtitle ? (
                      <span className="trace-subtitle">{block.subtitle}</span>
                    ) : null}
                  </summary>
                  <div className="trace-body">
                    {block.kind === "tool" ? (
                      <ToolTraceBlock block={block} />
                    ) : (
                      <MessageMarkdown content={block.content} />
                    )}
                  </div>
                </details>
              )
            )}
          </div>
        ) : null}

        {hasWorkorders ? (
          <div className="message-bubble markdown-bubble workorder-bubble">
            {message.content ? (
              <div className="workorder-intro">
                <MessageMarkdown content={message.content} />
              </div>
            ) : null}
            <AlarmWorkorderBoard
              error={message.workordersError}
              inline
              loading={message.workordersLoading}
              notice={ticketActionNotice}
              onAction={onTicketAction}
              onRefresh={onTicketRefresh}
              workorders={message.workorders || []}
            />
          </div>
        ) : renderedMessageContent ? (
          <div
            className={
              isStreamingMessage
                ? "message-bubble streaming-bubble markdown-bubble"
                : "message-bubble markdown-bubble"
            }
          >
            <MessageMarkdown
              content={renderedMessageContent}
              isStreaming={isStreamingMessage}
            />
            {isStreamingMessage ? <span className="streaming-cursor" /> : null}
          </div>
        ) : null}

        {message.type === "agent" && copyableContent && !hasWorkorders && !isStreamingMessage ? (
          <div className="message-copy-row">
            <CopyActionButton
              text={String(copyableContent || "").trim()}
              label="复制回复"
              buttonClassName="message-copy-btn"
              iconClassName="message-copy-icon"
            />
          </div>
        ) : null}

        {shouldShowDisposalOperation ? (
          <DisposalOperationCard
            action={effectiveDisposalOperation}
            onExecute={() => onDisposalAction(message.id, effectiveDisposalOperation)}
          />
        ) : null}

        {faultScenarioResult ? (
          <FaultScenarioResultCard pageTheme={pageTheme} result={faultScenarioResult} />
        ) : null}

        {message.workflow && !message.workflowDone ? (
          <div className="workflow-container">
            <div className="workflow-header">
              <div className="workflow-title">
                <i className="fas fa-cogs" /> 执行中...
              </div>
              <div className="workflow-progress">
                {Math.round(((message.currentStep + 1) / message.workflow.length) * 100)}
                %
              </div>
            </div>
            <div className="workflow-steps">
              {message.workflow.map((step: string, index: number) => (
                <div
                  key={step}
                  className={
                    index < message.currentStep
                      ? "workflow-step completed"
                      : index === message.currentStep
                      ? "workflow-step executing"
                      : "workflow-step"
                  }
                >
                  <div
                    className={
                      index < message.currentStep
                        ? "step-icon done"
                        : index === message.currentStep
                        ? "step-icon running"
                        : "step-icon pending"
                    }
                  >
                    <i
                      className={
                        index < message.currentStep
                          ? "fas fa-check"
                          : index === message.currentStep
                          ? "fas fa-spinner fa-spin"
                          : "fas fa-circle"
                      }
                    />
                  </div>
                  <div className="step-content">
                    <h4>{step}</h4>
                    <p>
                      {message.workflowDescriptions?.[index]
                        || employeeStepDescriptions[currentEmployee.id]?.[index]
                        || "处理中..."}
                    </p>
                  </div>
                  <div
                    className={
                      index < message.currentStep ? "step-time success" : "step-time"
                    }
                  >
                    {index < message.currentStep ? message.stepTimes[index] || "1s" : "--"}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {message.result ? (
          <div className="result-card">
            <div className="result-header">
              <div className="result-title">
                <i className="fas fa-check-circle" /> {message.result.title}
              </div>
              <span className="result-badge">{message.result.badge}</span>
            </div>
            <div className="result-metrics">
              {message.result.metrics.map((metric: any) => (
                <div key={metric.label} className="metric-box">
                  <div className={metric.highlight ? "metric-value highlight" : "metric-value"}>
                    {metric.value}
                  </div>
                  <div className="metric-label">{metric.label}</div>
                </div>
              ))}
            </div>
            {message.result.resources?.length ? (
              <div className="resource-grid">
                {message.result.resources.map((resource: any) => (
                  <div key={resource.name} className="resource-item">
                    <div className={`resource-icon ${resource.type}`}>
                      <i className={`fas ${resource.icon}`} />
                    </div>
                    <div className="resource-info">
                      <h5>{resource.name}</h5>
                      <p>{resource.desc}</p>
                    </div>
                    <span className="resource-status">{resource.status}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
});

function CopyGlyph({
  copied,
  className = "",
}: {
  copied: boolean;
  className?: string;
}) {
  if (copied) {
    return (
      <svg
        className={`${className} success`.trim()}
        viewBox="0 0 16 16"
        aria-hidden="true"
      >
        <path d="M3.5 8.25 6.25 11l6.25-6.25" />
      </svg>
    );
  }

  return (
    <svg
      className={`${className} copy`.trim()}
      viewBox="0 0 1024 1024"
      overflow="hidden"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M161.744 322.8864a69.6768 69.6768 0 0 1 15.6768-23.8656 69.6768 69.6768 0 0 1 23.8656-15.68A69.7824 69.7824 0 0 1 227.2 278.4h448c8.9504 0 17.5904 1.648 25.9136 4.944a69.6256 69.6256 0 0 1 23.8656 15.6768 69.664 69.664 0 0 1 15.6768 23.8656A69.7664 69.7664 0 0 1 745.6 348.8v448c0 8.9504-1.648 17.5904-4.944 25.9136a69.6128 69.6128 0 0 1-15.6768 23.8656 69.6736 69.6736 0 0 1-23.8656 15.6768A69.7728 69.7728 0 0 1 675.2 867.2H227.2c-8.9536 0-17.5904-1.648-25.9136-4.944a69.664 69.664 0 0 1-23.8656-15.6768 69.6256 69.6256 0 0 1-15.68-23.8656A69.7856 69.7856 0 0 1 156.8 796.8V348.8c0-8.9536 1.648-17.5904 4.944-25.9136zM227.2 803.2h448c1.7664 0 3.2736-0.624 4.5248-1.8752 1.2512-1.2512 1.8752-2.7584 1.8752-4.5248V348.8c0-1.7664-0.624-3.2768-1.8752-4.5248A6.1696 6.1696 0 0 0 675.2 342.4H227.2c-1.7664 0-3.2768 0.624-4.5248 1.8752-1.248 1.248-1.8752 2.7584-1.8752 4.5248v448c0 1.7664 0.624 3.2736 1.8752 4.5248 1.248 1.2512 2.7584 1.8752 4.5248 1.8752z" />
      <path d="M811.776 161.1584a95.1872 95.1872 0 0 1 30.5056 20.56 95.2096 95.2096 0 0 1 20.56 30.5056A94.96 94.96 0 0 1 870.4 249.6v390.4c0 17.6736-14.3264 32-32 32s-32-14.3264-32-32V249.6a31.76 31.76 0 0 0-9.3728-22.6272A31.8016 31.8016 0 0 0 774.4 217.6H384c-17.6736 0-32-14.3264-32-32s14.3264-32 32-32h390.4c13.008 0 25.4656 2.5184 37.376 7.5584z" />
    </svg>
  );
}

function CopyActionButton({
  text,
  label,
  buttonClassName,
  iconClassName,
}: {
  text: string;
  label: string;
  buttonClassName: string;
  iconClassName: string;
}) {
  const [copied, setCopied] = useState(false);
  const resetTimerRef = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (resetTimerRef.current) {
        window.clearTimeout(resetTimerRef.current);
      }
    },
    [],
  );

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (resetTimerRef.current) {
        window.clearTimeout(resetTimerRef.current);
      }
      resetTimerRef.current = window.setTimeout(() => {
        setCopied(false);
        resetTimerRef.current = null;
      }, 1600);
    } catch (error) {
      console.error("Failed to copy content:", error);
    }
  };

  return (
    <button
      type="button"
      className={buttonClassName}
      onClick={() => void handleCopy()}
      aria-label={copied ? "已复制" : label}
      title={copied ? "已复制" : label}
    >
      <CopyGlyph copied={copied} className={iconClassName} />
    </button>
  );
}

function ResponseTraceBlock({
  block,
  isStreaming = false,
}: {
  block: any;
  isStreaming?: boolean;
}) {
  const rich = isRichResponseContent(block.content);

  if (!rich) {
    return (
      <div className="response-trace-inline markdown-bubble">
        <MessageMarkdown content={block.content} isStreaming={isStreaming} />
        {isStreaming ? <span className="streaming-cursor" /> : null}
      </div>
    );
  }

  return (
    <div className="response-trace-rich">
      <div
        className={
          isStreaming
            ? "message-bubble streaming-bubble markdown-bubble response-trace-bubble"
            : "message-bubble markdown-bubble response-trace-bubble"
        }
      >
        <MessageMarkdown content={block.content} isStreaming={isStreaming} />
        {isStreaming ? <span className="streaming-cursor" /> : null}
      </div>
      {!isStreaming ? (
        <div className="message-copy-row">
          <CopyActionButton
            text={String(block.content || "").trim()}
            label="复制回复"
            buttonClassName="message-copy-btn"
            iconClassName="message-copy-icon"
          />
        </div>
      ) : null}
    </div>
  );
}

function isRichResponseContent(content: string) {
  const normalized = String(content || "");
  return (
    extractVisualBlocks(normalized).length > 0 ||
    /(^|\n)\s*#{1,6}\s+\S/m.test(normalized) ||
    /(^|\n)\s*\|.+\|/m.test(normalized) ||
    normalized.includes("```")
  );
}

function ToolTraceBlock({ block }: { block: any }) {
  const sections = [
    { key: "input", label: "Input", content: block.inputContent },
    { key: "output", label: "Output", content: block.outputContent },
  ].filter((section) => section.content);

  if (!sections.length) {
    return <MessageMarkdown content={block.content} />;
  }

  return (
    <div className="tool-trace-stack">
      {sections.map((section) => (
        <ToolTracePanel
          key={`${block.id}-${section.key}`}
          label={section.label}
          content={section.content}
          panelClassName={section.key}
        />
      ))}
    </div>
  );
}

function ToolTracePanel({
  label,
  content,
  panelClassName,
}: {
  label: string;
  content: string;
  panelClassName: string;
}) {
  const text = getToolTracePayloadText(content);

  return (
    <section className={`tool-trace-panel ${panelClassName}`}>
      <div className="tool-trace-panel-header">
        <span>{label}</span>
        <CopyActionButton
          text={text}
          label={`复制${label}`}
          buttonClassName="tool-trace-copy-btn"
          iconClassName="tool-trace-copy-icon"
        />
      </div>
      <div className="tool-trace-panel-body">
        <ToolTracePayload content={content} />
      </div>
    </section>
  );
}

function getToolTracePayloadText(content: string) {
  const normalized = String(content || "").trim();
  const fencedMatch = normalized.match(/^```([a-zA-Z0-9_-]+)?\n([\s\S]*?)\n```$/);
  return fencedMatch ? fencedMatch[2] : normalized;
}

function ToolTracePayload({ content }: { content: string }) {
  const text = getToolTracePayloadText(content);

  return (
    <pre className="tool-trace-code">
      <code>{text}</code>
    </pre>
  );
}

export const MessageMarkdown = memo(function MessageMarkdown({
  content,
  isStreaming = false,
}: {
  content: string;
  isStreaming?: boolean;
}) {
  const visualBlocks = extractVisualBlocks(content);
  const normalizedContent = stripFrontmatter(normalizeMarkdownDisplayContent(content, {
    isStreaming,
  }));
  const isDarkTheme =
    typeof document !== "undefined"
    && document.querySelector(".portal-digital-employee")?.classList.contains("theme-dark");
  const markdownThemeClass = isDarkTheme ? "x-markdown-dark" : "x-markdown-light";
  const hasText = Boolean(normalizedContent.trim());
  const visualContainer = visualBlocks.length ? (
    <div style={{ display: "grid", gap: 16, marginTop: hasText && !isStreaming ? 16 : 0, marginBottom: isStreaming && hasText ? 16 : 0 }}>
      {visualBlocks.map((block, index) =>
        block.type === "echarts" ? (
          <EChartsBlock
            key={`echarts-${index}`}
            chart={block.raw}
          />
        ) : block.type === "portal-visualization" ? (
          <PortalVisualizationBlock
            key={`portal-visualization-${index}`}
            raw={block.raw}
          />
        ) : null,
      )}
    </div>
  ) : null;

  return (
    <>
      {isStreaming ? visualContainer : null}
      <PortalQwenPawMarkdown
        className={`portal-x-markdown ${markdownThemeClass}`}
        content={normalizedContent}
        isStreaming={isStreaming}
      />
      {!isStreaming ? visualContainer : null}
    </>
  );
});

function stripFrontmatter(content: string) {
  return String(content || "").replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "");
}
