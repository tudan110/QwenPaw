import { useMemo } from "react";
import {
  DeferredEChartsBlock,
  DeferredMermaidBlock,
} from "./DeferredVisualizationBlocks";

interface VisualizationChart {
  id?: string;
  kind?: string;
  option?: Record<string, unknown>;
  chart?: string;
}

interface VisualizationPayload {
  type?: string;
  charts?: VisualizationChart[];
}

interface PortalVisualizationBlockProps {
  raw: string;
}

function parsePayload(raw: string): VisualizationPayload | null {
  try {
    const parsed = JSON.parse(String(raw || "").trim()) as VisualizationPayload;
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    return parsed;
  } catch (error) {
    console.error("Failed to parse portal visualization payload:", error);
    return null;
  }
}

export function PortalVisualizationBlock({ raw }: PortalVisualizationBlockProps) {
  const payload = useMemo(() => parsePayload(raw), [raw]);

  if (!payload?.charts?.length) {
    return (
      <pre
        style={{
          padding: 16,
          background: "#fff1f0",
          border: "1px solid #ffa39e",
          borderRadius: 6,
          overflow: "auto",
        }}
      >
        <code>{raw}</code>
      </pre>
    );
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {payload.charts.map((chart, index) => {
        if (chart.kind === "mermaid") {
          return (
            <DeferredMermaidBlock
              key={chart.id || `mermaid-${index}`}
              chart={String(chart.chart || "")}
            />
          );
        }

        return (
          <DeferredEChartsBlock
            key={chart.id || `echarts-${index}`}
            chart={JSON.stringify(chart.option || {})}
          />
        );
      })}
    </div>
  );
}
