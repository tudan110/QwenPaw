import { memo, Suspense, useEffect, useRef, useState } from "react";
import { employeeStepDescriptions } from "../../data/portalData";
import { DeferredEChartsBlock } from "../../components/DeferredVisualizationBlocks";
import { PortalVisualizationBlock } from "../../components/PortalVisualizationBlock";
import { PortalQwenPawMarkdown } from "../../components/PortalQwenPawMarkdown";
import { lazyNamed } from "../../utils/lazyNamed";
import {
  extractVisualBlocks,
  extractRenderableContentSegments,
  extractPortalActionPayload,
  getSeverityClassName,
  normalizeMarkdownDisplayContent,
  PORTAL_INSPECTION_CARD_MARKER,
  unwrapPortalInspectionCardContent,
} from "./helpers";
import { FaultScenarioResultCard } from "./faultScenarioComponents";

const ResourceImportConversationCard = lazyNamed(
  () => import("./resourceImportConversationCard"),
  "ResourceImportConversationCard",
);
const AlarmAnalystCardPanel = lazyNamed(
  () => import("./alarmAnalystCardComponents"),
  "AlarmAnalystCardPanel",
);
const InspectionAnalystCardPanel = lazyNamed(
  () => import("./inspectionAnalystCardComponents"),
  "InspectionAnalystCardPanel",
);

const deferredMessageCardFallback = (
  <div className="history-empty" style={{ minHeight: 180 }}>
    <i className="fas fa-spinner fa-spin" />
    <p>正在加载内容...</p>
  </div>
);

function looksLikeInspectionReportCardContent(content: string) {
  const normalized = String(content || "").replace(/\r\n/g, "\n");
  return (
    (
      normalized.includes(PORTAL_INSPECTION_CARD_MARKER)
      || /(?:^|\n)##+\s*.*巡检结果/um.test(normalized)
    )
    && /(?:^|\n)##+\s*.*基本信息/um.test(normalized)
    && /(?:^|\n)##+\s*.*指标数据/um.test(normalized)
  );
}

function looksLikeInspectionHealthAssessmentCardContent(content: string) {
  const normalized = String(content || "").replace(/\r\n/g, "\n");
  return (
    /(?:^|\n)##+\s*.*健康状态评估/um.test(normalized)
    && /总体评分/u.test(normalized)
    && /(健康项|亚健康项|病理项|建议优先级)/u.test(normalized)
  );
}

function shouldRenderInspectionAnalystCard(content: string) {
  return (
    looksLikeInspectionReportCardContent(content)
    || looksLikeInspectionHealthAssessmentCardContent(content)
  );
}

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
  agentId,
  currentEmployee,
  isStreamingMessage,
  message,
  onDisposalAction,
  onResourceImportBackToConfirm,
  onResourceImportBuildTopology,
  onResourceImportConfirmStructure,
  onResourceImportContinue,
  onResourceImportOpenSystemTopology,
  onResourceImportParseFailed,
  onResourceImportParseResolved,
  onResourceImportReturnToUpload,
  onResourceImportStartParse,
  onResourceImportScrollToStage,
  onResourceImportSubmitImport,
  onResourceImportUploadFiles,
  releaseResourceImportFiles,
  resolveResourceImportFiles,
  pageTheme,
  onTicketAction,
  onTicketRefresh,
  ticketActionNotice,
}: any) {
  const allBlocks = message.processBlocks || [];
  const condensedBlocks = condenseBackgroundPollingBlocks(allBlocks);
  const hasInterleavedResponses = allBlocks.some(
    (block: any) => block?.kind === "response" && block.content,
  );
  const liveMessageContent = String(message.content || "");
  const normalizedLiveMessageContent = liveMessageContent.trim();

  // Interleaved mode: response blocks exist in processBlocks (loaded history)
  // Legacy mode: no response blocks, text lives in message.content (streaming)
  const displayBlocks = hasInterleavedResponses
    ? condensedBlocks
    : condensedBlocks.filter((block: any) => block?.kind !== "response");
  const hasWorkorders =
    Boolean(message.workorders?.length) ||
    Boolean(message.workordersLoading) ||
    Boolean(message.workordersError);
  const hasResourceImportFlow = Boolean(message.resourceImportFlow);
  const alarmAnalystCard = message.type === "agent" ? message.alarmAnalystCard : null;
  const hasAlarmAnalystCard = Boolean(alarmAnalystCard);
  const faultScenarioResult = message.faultScenarioResult;
  const primaryResponseBlock =
    [...displayBlocks].reverse().find((block: any) => block?.kind === "response" && block.content) || null;
  const auxiliaryTraceBlocks = displayBlocks.filter(
    (block: any) => !(primaryResponseBlock && block?.kind === "response" && block.id === primaryResponseBlock.id),
  );
  const trailingResponseContent = [...displayBlocks].reverse().find(
    (block: any) => block?.kind === "response" && block.id !== primaryResponseBlock?.id && block.content,
  )?.content || "";
  const liveContentDuplicatesTrace = Boolean(normalizedLiveMessageContent) && auxiliaryTraceBlocks.some(
    (block: any) => {
      const normalizedBlockContent = String(block?.content || "").trim();
      return normalizedBlockContent && (
        normalizedBlockContent === normalizedLiveMessageContent
        || normalizedBlockContent.endsWith(normalizedLiveMessageContent)
        || normalizedLiveMessageContent.endsWith(normalizedBlockContent)
      );
    },
  );
  const renderedMessageContent = primaryResponseBlock
    ? (
        isStreamingMessage
          ? (liveMessageContent || primaryResponseBlock.content || "")
          : String(primaryResponseBlock.content || liveMessageContent || "")
      )
    : (
        liveContentDuplicatesTrace
          ? trailingResponseContent
          : (liveMessageContent || trailingResponseContent)
      );
  const effectiveDisposalOperation =
    message.disposalOperation ||
    extractPortalActionPayload(renderedMessageContent || message.content || "");
  const shouldShowDisposalOperation =
    Boolean(effectiveDisposalOperation) &&
    effectiveDisposalOperation.status !== "success" &&
    !message.hideDisposalOperation;
  const isInspectionAnalystCardCandidate =
    message.type === "agent"
    && currentEmployee?.id === "inspection"
    && !isStreamingMessage
    && shouldRenderInspectionAnalystCard(renderedMessageContent);
  const copyableContent = String(
    renderedMessageContent || alarmAnalystCard?.rawReportMarkdown || "",
  ).trim();
  const traceBundleSubtitle = buildTraceBundleSubtitle(auxiliaryTraceBlocks);
  const [isTraceBundleOpen, setIsTraceBundleOpen] = useState(false);
  const wasStreamingTraceBundleRef = useRef(false);

  useEffect(() => {
    if (!auxiliaryTraceBlocks.length) {
      wasStreamingTraceBundleRef.current = false;
      setIsTraceBundleOpen(false);
      return;
    }

    if (isStreamingMessage) {
      wasStreamingTraceBundleRef.current = true;
      setIsTraceBundleOpen(true);
      return;
    }

    if (wasStreamingTraceBundleRef.current) {
      setIsTraceBundleOpen(false);
      wasStreamingTraceBundleRef.current = false;
    }
  }, [auxiliaryTraceBlocks.length, isStreamingMessage]);

  return (
    <div
      id={`message-${message.id}`}
      className={message.type === "user" ? "message user" : "message agent"}
    >
      <div
        className="message-avatar"
        style={message.type === "agent" ? { background: message.gradient } : {}}
      >
        <i className={`fas ${message.type === "user" ? "fa-user" : message.icon}`} />
      </div>
        <div className="message-content">
          {auxiliaryTraceBlocks.length ? (
          <details
            className="trace-block trace-bundle"
            open={isTraceBundleOpen}
            onToggle={(event) => {
              setIsTraceBundleOpen(event.currentTarget.open);
            }}
          >
            <summary className="trace-summary">
              <span className="trace-label">
                <i className="fas fa-layer-group" />
                过程记录
              </span>
              {traceBundleSubtitle ? (
                <span className="trace-subtitle">{traceBundleSubtitle}</span>
              ) : null}
            </summary>
            <div className="trace-body trace-bundle-body">
              {auxiliaryTraceBlocks.map((block: any, index: number) => (
                <TraceEntry
                  key={block.id || `${block.kind}-${index}`}
                  block={block}
                  isStreaming={isStreamingMessage}
                />
              ))}
            </div>
          </details>
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
        ) : hasResourceImportFlow ? (
          <div className="message-bubble markdown-bubble resource-import-flow-bubble">
            <Suspense fallback={deferredMessageCardFallback}>
              <ResourceImportConversationCard
                agentId={agentId}
                message={message}
                onBackToConfirm={onResourceImportBackToConfirm}
                onBuildTopology={onResourceImportBuildTopology}
                onConfirmStructure={onResourceImportConfirmStructure}
                onContinueImport={onResourceImportContinue}
                onOpenSystemTopology={onResourceImportOpenSystemTopology}
                onParseFailed={onResourceImportParseFailed}
                onParseResolved={onResourceImportParseResolved}
                onReturnToUpload={onResourceImportReturnToUpload}
                onStartParse={onResourceImportStartParse}
                onScrollToStage={onResourceImportScrollToStage}
                onSubmitImport={onResourceImportSubmitImport}
                onUploadFiles={onResourceImportUploadFiles}
                releaseFiles={releaseResourceImportFiles}
                resolveFiles={resolveResourceImportFiles}
              />
            </Suspense>
          </div>
        ) : hasAlarmAnalystCard ? (
          <div className="message-bubble markdown-bubble alarm-analyst-card-bubble">
            <Suspense fallback={deferredMessageCardFallback}>
              <AlarmAnalystCardPanel card={alarmAnalystCard} />
            </Suspense>
          </div>
        ) : isInspectionAnalystCardCandidate ? (
          <div className="message-bubble markdown-bubble inspection-analyst-card-bubble">
            <Suspense fallback={deferredMessageCardFallback}>
              <InspectionAnalystCardPanel content={renderedMessageContent} />
            </Suspense>
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

        {message.type === "agent"
        && copyableContent
        && !hasWorkorders
        && !isStreamingMessage
        ? (
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

function condenseBackgroundPollingBlocks(blocks: any[] = []) {
  const condensed: any[] = [];

  for (let index = 0; index < blocks.length; index += 1) {
    const current = blocks[index];
    if (!isPollingToolBlock(current)) {
      condensed.push(current);
      continue;
    }

    const toolBlocks = [current];
    const waitingResponses: any[] = [];
    let cursor = index + 1;

    while (cursor < blocks.length) {
      const candidate = blocks[cursor];
      if (isWaitingPollingResponse(candidate)) {
        waitingResponses.push(candidate);
        cursor += 1;
        continue;
      }
      if (isPollingToolBlock(candidate)) {
        toolBlocks.push(candidate);
        cursor += 1;
        continue;
      }
      break;
    }

    if (toolBlocks.length === 1 && waitingResponses.length === 0) {
      condensed.push(current);
      continue;
    }

    condensed.push(buildPollingSummaryBlock(toolBlocks, waitingResponses));
    index = cursor - 1;
  }

  return condensed;
}

function isPollingToolBlock(block: any) {
  return block?.kind === "tool" && block?.toolName === "check_agent_task";
}

function isWaitingPollingResponse(block: any) {
  if (block?.kind !== "response") {
    return false;
  }
  const text = String(block.content || "").trim();
  if (!text || text.length > 120) {
    return false;
  }
  return /继续(等待|查询)|任务仍在(运行|处理)|稍后|轮询|查询任务状态|待查询结果|pending|running/i.test(text);
}

function buildPollingSummaryBlock(toolBlocks: any[], waitingResponses: any[]) {
  const latestTool = toolBlocks[toolBlocks.length - 1] || toolBlocks[0];
  const latestWaitingText = [...waitingResponses]
    .reverse()
    .map((item) => String(item.content || "").trim())
    .find(Boolean);
  const pollCount = toolBlocks.length;
  const foldedCount = Math.max(pollCount - 1, 0) + waitingResponses.length;
  const summaryLines = [
    `后台协同任务正在处理中，已自动轮询 ${pollCount} 次。`,
    foldedCount > 0 ? `中间 ${foldedCount} 条轮询日志已折叠显示。` : "",
    latestWaitingText ? `最近状态：${latestWaitingText}` : "最近状态：任务仍在运行，等待最终结果返回。",
  ].filter(Boolean);

  return {
    ...latestTool,
    id: `polling-summary-${toolBlocks[0]?.id || Date.now()}`,
    title: "后台协同轮询",
    subtitle: `已轮询 ${pollCount} 次`,
    icon: "fa-hourglass-half",
    inputContent: "",
    outputContent: summaryLines.join("\n"),
    content: summaryLines.join("\n"),
    defaultOpen: false,
  };
}

function buildTraceBundleSubtitle(blocks: any[] = []) {
  if (!blocks.length) {
    return "";
  }

  const thinkingCount = blocks.filter((block) => block?.kind === "thinking").length;
  const toolCount = blocks.filter((block) => block?.kind === "tool").length;
  const responseCount = blocks.filter((block) => block?.kind === "response").length;
  const segments = [
    thinkingCount ? `思考 ${thinkingCount}` : "",
    toolCount ? `工具 ${toolCount}` : "",
    responseCount ? `中间回复 ${responseCount}` : "",
  ].filter(Boolean);

  return segments.join(" · ") || `${blocks.length} 条记录`;
}

function TraceEntry({
  block,
  isStreaming = false,
}: {
  block: any;
  isStreaming?: boolean;
}) {
  if (block?.kind === "response") {
    return (
      <section className="trace-entry response">
        <div className="trace-entry-caption">
          <span className="trace-label">
            <i className="fas fa-comment-dots" />
            中间回复
          </span>
          <span className="trace-subtitle">过程消息</span>
        </div>
        <ResponseTraceBlock block={block} isStreaming={isStreaming} />
      </section>
    );
  }

  return (
    <details
      className={`trace-block trace-entry ${block?.kind || "misc"}`}
      open={block?.defaultOpen}
    >
      <summary className="trace-summary">
        <span className="trace-label">
          <i className={`fas ${block?.icon || "fa-bars-progress"}`} />
          {block?.title || (block?.kind === "thinking" ? "Thinking" : "过程记录")}
        </span>
        {block?.subtitle ? (
          <span className="trace-subtitle">{block.subtitle}</span>
        ) : null}
      </summary>
      <div className="trace-body">
        {block?.kind === "tool" ? (
          <ToolTraceBlock block={block} />
        ) : (
          <MessageMarkdown content={block?.content || ""} isStreaming={isStreaming} />
        )}
      </div>
    </details>
  );
}

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
  const isDarkTheme =
    typeof document !== "undefined"
    && document.querySelector(".portal-digital-employee")?.classList.contains("theme-dark");
  const markdownThemeClass = isDarkTheme ? "x-markdown-dark" : "x-markdown-light";
  const normalizedContent = stripFrontmatter(unwrapPortalInspectionCardContent(normalizeMarkdownDisplayContent(content, {
    isStreaming,
  })));
  const streamingContent = String(content || "");

  if (isStreaming) {
    return (
      <PortalQwenPawMarkdown
        className={`portal-x-markdown ${markdownThemeClass}`}
        content={streamingContent}
        isStreaming={isStreaming}
      />
    );
  }

  const renderableSegments = extractRenderableContentSegments(content);
  const hasVisualSegments = renderableSegments.some((segment) => segment.type !== "markdown");

  if (!hasVisualSegments) {
    return (
      <PortalQwenPawMarkdown
        className={`portal-x-markdown ${markdownThemeClass}`}
        content={normalizedContent}
        isStreaming={false}
      />
    );
  }

  return (
    <>
      {renderableSegments.map((segment, index) => {
        if (segment.type === "markdown") {
          const segmentContent = stripFrontmatter(unwrapPortalInspectionCardContent(normalizeMarkdownDisplayContent(segment.content, {
            isStreaming: false,
          })));
          if (!segmentContent.trim()) {
            return null;
          }

          return (
            <PortalQwenPawMarkdown
              key={`markdown-${index}`}
              className={`portal-x-markdown ${markdownThemeClass}`}
              content={segmentContent}
              isStreaming={false}
            />
          );
        }

        return (
          <div
            key={`${segment.type}-${index}`}
            style={{ display: "grid", gap: 16, margin: "16px 0" }}
          >
            {segment.type === "echarts" ? (
              <DeferredEChartsBlock chart={segment.raw} />
            ) : (
              <PortalVisualizationBlock raw={segment.raw} />
            )}
          </div>
        );
      })}
    </>
  );
});

function stripFrontmatter(content: string) {
  return String(content || "").replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "");
}
