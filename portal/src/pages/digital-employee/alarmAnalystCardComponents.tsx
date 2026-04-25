import { memo, useMemo } from "react";

import { PortalQwenPawMarkdown } from "../../components/PortalQwenPawMarkdown";
import { DeferredEChartsBlock } from "../../components/DeferredVisualizationBlocks";
import type { AlarmAnalystCardV1 } from "../../alarm-analyst/shared";
import { normalizeMarkdownDisplayContent } from "./helpers";

function buildTopologyChart(card: AlarmAnalystCardV1) {
  const nodes = Array.isArray(card.topology?.nodes) ? card.topology.nodes : [];
  const edges = Array.isArray(card.topology?.edges) ? card.topology.edges : [];
  if (!nodes.length) {
    return "";
  }

  return JSON.stringify({
    title: { text: "影响拓扑" },
    tooltip: {},
    animationDurationUpdate: 300,
    series: [
      {
        type: "graph",
        layout: "force",
        roam: true,
        draggable: true,
        label: { show: true },
        force: {
          repulsion: 260,
          edgeLength: 120,
        },
        data: nodes.map((node: any) => ({
          ...node,
          value: node?.value || 1,
          category: node?.category || 0,
          symbolSize: node?.symbolSize || 42,
          itemStyle: card.topology.highlightedNodeIds?.includes(String(node?.id || node?.name || ""))
            ? { color: "#ef4444" }
            : node?.itemStyle,
        })),
        links: edges.map((edge: any) => ({
          ...edge,
          lineStyle: edge?.lineStyle || { opacity: 0.8, width: 2 },
        })),
      },
    ],
  });
}

function AlarmAnalystMarkdown({ content }: { content: string }) {
  const isDarkTheme =
    typeof document !== "undefined"
    && document.querySelector(".portal-digital-employee")?.classList.contains("theme-dark");
  const markdownThemeClass = isDarkTheme ? "x-markdown-dark" : "x-markdown-light";
  const normalizedContent = normalizeMarkdownDisplayContent(content);

  return (
    <PortalQwenPawMarkdown
      className={`portal-x-markdown ${markdownThemeClass}`}
      content={normalizedContent}
      isStreaming={false}
    />
  );
}

export const AlarmAnalystCardPanel = memo(function AlarmAnalystCardPanel({
  card,
}: {
  card: AlarmAnalystCardV1;
}) {
  const topologyChart = useMemo(() => buildTopologyChart(card), [card]);

  return (
    <div className="alarm-analyst-card-stack">
      <section className="alarm-analyst-card alarm-analyst-summary-card">
        <div className="alarm-analyst-card-header">
          <div>
            <div className="alarm-analyst-card-eyebrow">根因分析结论</div>
            <h3>{card.summary.title || "故障根因分析"}</h3>
          </div>
          <div className="alarm-analyst-summary-badges">
            {card.summary.status ? (
              <span className={`alarm-analyst-badge status-${card.summary.status}`}>
                {card.summary.status}
              </span>
            ) : null}
            {card.summary.confidence ? (
              <span className="alarm-analyst-badge">{card.summary.confidence}</span>
            ) : null}
            {card.summary.severity ? (
              <span className="alarm-analyst-badge">{card.summary.severity}</span>
            ) : null}
          </div>
        </div>
        <p className="alarm-analyst-summary-text">{card.summary.conclusion}</p>
        {card.rootCause?.reason ? (
          <div className="alarm-analyst-root-cause">
            <strong>根因锚点：</strong>
            <span>
              {card.rootCause.resourceName || card.rootCause.resourceId || "未识别资源"}
              {card.rootCause.ciId ? `（CI ID ${card.rootCause.ciId}）` : ""}
              {" · "}
              {card.rootCause.reason}
            </span>
          </div>
        ) : null}
      </section>

      {(card.impact.affectedApplications.length || card.impact.affectedResources.length || card.impact.blastRadiusText) ? (
        <section className="alarm-analyst-card">
          <div className="alarm-analyst-card-eyebrow">影响范围</div>
          {card.impact.blastRadiusText ? (
            <p className="alarm-analyst-impact-text">{card.impact.blastRadiusText}</p>
          ) : null}
          <div className="alarm-analyst-impact-groups">
            {card.impact.affectedApplications.length ? (
              <div>
                <h4>受影响应用</h4>
                <div className="alarm-analyst-chip-list">
                  {card.impact.affectedApplications.map((item, index) => (
                    <span key={`${item.id || item.name}-${index}`} className="alarm-analyst-chip">
                      {item.name}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
            {card.impact.affectedResources.length ? (
              <div>
                <h4>受影响资源</h4>
                <div className="alarm-analyst-chip-list">
                  {card.impact.affectedResources.map((item, index) => (
                    <span key={`${item.id || item.name}-${index}`} className="alarm-analyst-chip">
                      {item.name}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </section>
      ) : null}

      {topologyChart ? (
        <section className="alarm-analyst-card">
          <div className="alarm-analyst-card-eyebrow">应用 / 资源拓扑</div>
          <div className="alarm-analyst-topology-panel">
            <DeferredEChartsBlock
              chart={topologyChart}
              style={{ height: 360 }}
              fallbackMinHeight={360}
            />
          </div>
        </section>
      ) : null}

      {card.recommendations.length ? (
        <section className="alarm-analyst-card">
          <div className="alarm-analyst-card-eyebrow">处置建议</div>
          <div className="alarm-analyst-recommendations">
            {card.recommendations.map((item, index) => (
              <article key={`${item.title}-${index}`} className="alarm-analyst-recommendation">
                <div className="alarm-analyst-recommendation-header">
                  <span className={`alarm-analyst-priority ${item.priority}`}>{item.priority}</span>
                  <h4>{item.title}</h4>
                </div>
                <p>{item.description}</p>
                {item.risk ? <div className="alarm-analyst-risk">风险：{item.risk}</div> : null}
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {card.evidence.length ? (
        <section className="alarm-analyst-card">
          <div className="alarm-analyst-card-eyebrow">证据摘要</div>
          <div className="alarm-analyst-evidence-list">
            {card.evidence.map((item, index) => (
              <article key={`${item.title}-${index}`} className="alarm-analyst-evidence-item">
                <span className="alarm-analyst-evidence-kind">{item.kind}</span>
                <div>
                  <h4>{item.title}</h4>
                  <p>{item.summary}</p>
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {card.rawReportMarkdown ? (
        <details className="alarm-analyst-raw-report">
          <summary>查看完整分析</summary>
          <div className="message-bubble markdown-bubble alarm-analyst-raw-report-body">
            <AlarmAnalystMarkdown content={card.rawReportMarkdown} />
          </div>
        </details>
      ) : null}
    </div>
  );
});
