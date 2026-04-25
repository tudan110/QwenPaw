import { Suspense } from "react";
import type { CSSProperties } from "react";
import { lazyNamed } from "../utils/lazyNamed";

const LazyEChartsBlock = lazyNamed(() => import("./EChartsBlock"), "EChartsBlock");
const LazyMermaidBlock = lazyNamed(() => import("./MermaidBlock"), "MermaidBlock");

function VisualizationFallback({
  label,
  minHeight,
  style,
}: {
  label: string;
  minHeight: number;
  style?: CSSProperties;
}) {
  return (
    <div
      style={{
        minHeight,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
        borderRadius: 16,
        border: "1px solid rgba(148, 163, 184, 0.18)",
        background:
          "linear-gradient(180deg, rgba(248, 250, 252, 0.96) 0%, rgba(255, 255, 255, 0.98) 100%)",
        color: "#64748b",
        ...style,
      }}
    >
      {label}
    </div>
  );
}

export function DeferredEChartsBlock({
  chart,
  style,
  fallbackMinHeight = 220,
}: {
  chart: string;
  style?: CSSProperties;
  fallbackMinHeight?: number;
}) {
  return (
    <Suspense
      fallback={
        <VisualizationFallback
          label="正在加载图表..."
          minHeight={fallbackMinHeight}
          style={style}
        />
      }
    >
      <LazyEChartsBlock chart={chart} style={style} />
    </Suspense>
  );
}

export function DeferredMermaidBlock({
  chart,
  fallbackMinHeight = 220,
}: {
  chart: string;
  fallbackMinHeight?: number;
}) {
  return (
    <Suspense
      fallback={
        <VisualizationFallback
          label="正在加载拓扑图..."
          minHeight={fallbackMinHeight}
        />
      }
    >
      <LazyMermaidBlock chart={chart} />
    </Suspense>
  );
}
