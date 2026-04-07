import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { employeeStepDescriptions } from "../../data/portalData";
import { EChartsBlock } from "../../components/EChartsBlock";
import { MermaidBlock } from "../../components/MermaidBlock";
import { PortalVisualizationBlock } from "../../components/PortalVisualizationBlock";
import {
  extractVisualBlocks,
  extractPortalActionPayload,
  getSeverityClassName,
  normalizeMarkdownDisplayContent,
} from "./helpers";

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
          <p>告警已触发故障速应，当前先展示待处置工单，后续可在此接入不同类型故障的处置流程。</p>
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
            <p>故障速应（告警驱动工单）</p>
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
  onTicketAction,
  onTicketRefresh,
  ticketActionNotice,
}: any) {
  const hasWorkorders =
    Boolean(message.workorders?.length) ||
    Boolean(message.workordersLoading) ||
    Boolean(message.workordersError);
  const effectiveDisposalOperation =
    message.disposalOperation || extractPortalActionPayload(message.content);
  const shouldShowDisposalOperation =
    Boolean(effectiveDisposalOperation) &&
    effectiveDisposalOperation.status !== "success" &&
    !message.hideDisposalOperation;

  return (
    <div className={message.type === "user" ? "message user" : "message agent"}>
      <div
        className="message-avatar"
        style={message.type === "agent" ? { background: message.gradient } : {}}
      >
        <i className={`fas ${message.type === "user" ? "fa-user" : message.icon}`} />
      </div>
      <div className="message-content">
        {message.processBlocks?.length ? (
          <div className="process-trace">
            {message.processBlocks.map((block: any) => (
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
                  <MessageMarkdown content={block.content} />
                </div>
              </details>
            ))}
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
        ) : message.content ? (
          <div
            className={
              isStreamingMessage
                ? "message-bubble streaming-bubble markdown-bubble"
                : "message-bubble markdown-bubble"
            }
          >
            <MessageMarkdown
              content={message.content}
              isStreaming={isStreamingMessage}
            />
            {isStreamingMessage ? <span className="streaming-cursor" /> : null}
          </div>
        ) : null}

        {shouldShowDisposalOperation ? (
          <DisposalOperationCard
            action={effectiveDisposalOperation}
            onExecute={() => onDisposalAction(message.id, effectiveDisposalOperation)}
          />
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

export const MessageMarkdown = memo(function MessageMarkdown({
  content,
  isStreaming = false,
}: {
  content: string;
  isStreaming?: boolean;
}) {
  const visualBlocks = extractVisualBlocks(content);
  const normalizedContent = normalizeMarkdownDisplayContent(content, {
    isStreaming,
  });
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
        ) : (
          <MermaidBlock
            key={`mermaid-${index}`}
            chart={block.raw}
          />
        ),
      )}
    </div>
  ) : null;

  return (
    <>
      {isStreaming ? visualContainer : null}
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node, ...props }) => (
            <a {...props} target="_blank" rel="noreferrer" />
          ),
          code: ({ node, className, children, inline, ...props }: any) => {
            return (
              <code className={className} {...props}>
                {children}
              </code>
            );
          },
        }}
      >
        {normalizedContent}
      </ReactMarkdown>
      {!isStreaming ? visualContainer : null}
    </>
  );
});
