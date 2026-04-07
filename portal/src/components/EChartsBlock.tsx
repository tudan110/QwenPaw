import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import ReactECharts from "echarts-for-react";
import * as echarts from "echarts";

const ECHARTS_RENDER_CACHE_MAX_ENTRIES = 100;

interface MockStreamMeta {
  enabled?: boolean;
  intervalMs?: number;
  batchSize?: number;
  initialVisiblePoints?: number;
  totalPoints?: number;
}

interface EChartsBlockProps {
  chart: string;
  style?: CSSProperties;
}

class BoundedMap<K, V> extends Map<K, V> {
  maxSize: number;

  constructor(maxSize: number) {
    super();
    this.maxSize = maxSize;
  }

  set(key: K, value: V) {
    if (!this.has(key) && this.size >= this.maxSize) {
      const firstKey = this.keys().next().value;
      if (firstKey !== undefined) {
        this.delete(firstKey);
      }
    }
    return super.set(key, value);
  }
}

const echartsRenderCache = new BoundedMap(ECHARTS_RENDER_CACHE_MAX_ENTRIES);

function parseEChartsConfig(chart: string) {
  const trimmedChart = chart.trim();
  if (!trimmedChart) return null;

  const cached = echartsRenderCache.get(trimmedChart);
  if (cached) return cached;

  try {
    const config = JSON.parse(trimmedChart);
    echartsRenderCache.set(trimmedChart, config);
    return config;
  } catch (e) {
    console.error("Failed to parse ECharts config:", e);
    return null;
  }
}

function cloneChartConfig<T>(config: T): T {
  return JSON.parse(JSON.stringify(config));
}

function stripRuntimeMeta(config: Record<string, any> | null) {
  if (!config) {
    return { option: null, mockStream: null };
  }
  const nextOption = cloneChartConfig(config);
  const mockStream = (nextOption.__mockStream || null) as MockStreamMeta | null;
  delete nextOption.__mockStream;
  return {
    option: nextOption,
    mockStream,
  };
}

function applyMockStreamPlayback(
  option: Record<string, any> | null,
  mockStream: MockStreamMeta | null,
  tick: number,
) {
  if (!option || !mockStream?.enabled) {
    return option;
  }

  const nextOption = cloneChartConfig(option);
  const totalPoints =
    Number(mockStream.totalPoints)
    || nextOption.xAxis?.data?.length
    || 0;
  const initialVisiblePoints = Math.min(
    Number(mockStream.initialVisiblePoints) || totalPoints,
    totalPoints,
  );
  const batchSize = Math.max(1, Number(mockStream.batchSize) || 1);
  const visibleCount = Math.min(totalPoints, initialVisiblePoints + (tick * batchSize));

  if (nextOption.xAxis?.data?.length) {
    nextOption.xAxis.data = nextOption.xAxis.data.slice(0, visibleCount);
  }

  if (Array.isArray(nextOption.series)) {
    nextOption.series = nextOption.series.map((series) => {
      const nextSeries = { ...series };
      if (Array.isArray(series.data)) {
        nextSeries.data = series.data.slice(0, visibleCount);
      }
      if (nextSeries.markPoint?.data?.length && nextOption.xAxis?.data?.length) {
        const visibleLabels = new Set(nextOption.xAxis.data);
        nextSeries.markPoint = {
          ...nextSeries.markPoint,
          data: nextSeries.markPoint.data.filter((item) =>
            visibleLabels.has(item?.coord?.[0]),
          ),
        };
      }
      if (nextSeries.markLine?.data?.length && nextOption.xAxis?.data?.length) {
        const visibleLabels = new Set(nextOption.xAxis.data);
        nextSeries.markLine = {
          ...nextSeries.markLine,
          data: nextSeries.markLine.data.filter((item) =>
            visibleLabels.has(item?.xAxis),
          ),
        };
      }
      return nextSeries;
    });
  }

  return nextOption;
}

export function EChartsBlock({ chart, style }: EChartsBlockProps) {
  const [error, setError] = useState("");
  const [playbackTick, setPlaybackTick] = useState(0);
  const parsedConfig = useMemo(() => {
    const config = parseEChartsConfig(chart);
    if (!config && chart.trim()) {
      setError("Invalid ECharts configuration");
      return null;
    }
    setError("");
    return config;
  }, [chart]);
  const { option: baseOption, mockStream } = useMemo(
    () => stripRuntimeMeta(parsedConfig),
    [parsedConfig],
  );
  const option = useMemo(
    () => applyMockStreamPlayback(baseOption, mockStream, playbackTick),
    [baseOption, mockStream, playbackTick],
  );

  useEffect(() => {
    setPlaybackTick(0);
  }, [chart]);

  useEffect(() => {
    if (!mockStream?.enabled) {
      return undefined;
    }
    const totalPoints = Number(mockStream.totalPoints) || 0;
    const initialVisiblePoints = Math.min(
      Number(mockStream.initialVisiblePoints) || totalPoints,
      totalPoints,
    );
    const batchSize = Math.max(1, Number(mockStream.batchSize) || 1);
    if (initialVisiblePoints >= totalPoints) {
      return undefined;
    }
    const timerId = window.setInterval(() => {
      setPlaybackTick((currentTick) => {
        const remainingTicks = Math.ceil((totalPoints - initialVisiblePoints) / batchSize);
        if (currentTick >= remainingTicks) {
          window.clearInterval(timerId);
          return currentTick;
        }
        return currentTick + 1;
      });
    }, Math.max(80, Number(mockStream.intervalMs) || 180));
    return () => window.clearInterval(timerId);
  }, [mockStream]);

  if (error) {
    return (
      <pre
        style={{
          padding: 16,
          background: "#fff1f0",
          border: "1px solid #ffa39e",
          borderRadius: 6,
          overflow: "auto",
          ...style,
        }}
      >
        <code>{chart}</code>
      </pre>
    );
  }

  if (!option) {
    return null;
  }

  return (
    <div
      style={{
        width: "100%",
        minHeight: 360,
        background:
          "linear-gradient(180deg, rgba(248, 250, 252, 0.96) 0%, rgba(255, 255, 255, 0.98) 100%)",
        borderRadius: 16,
        padding: 12,
        border: "1px solid rgba(148, 163, 184, 0.18)",
        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.7), 0 8px 24px rgba(15, 23, 42, 0.05)",
        ...style,
      }}
    >
      <ReactECharts
        echarts={echarts}
        option={option}
        style={{ height: "100%", width: "100%", minHeight: 360 }}
        opts={{ renderer: "canvas" }}
        notMerge={true}
        lazyUpdate={true}
        theme="light"
      />
    </div>
  );
}
