import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import ReactECharts from "echarts-for-react";
import * as echarts from "echarts";

const ECHARTS_RENDER_CACHE_MAX_ENTRIES = 100;
const ECHARTS_FUNCTION_TOKEN_PREFIX = "__ECHARTS_FUNCTION__";
const ECHARTS_FULLSCREEN_FEATURE = "myFullscreen";
const ECHARTS_FULLSCREEN_ICON = "path://M192 128h256v64H256v192h-64V128zm384 0h256v256h-64V192H576v-64zM192 576h64v192h192v64H192V576zm576 0h64v256H576v-64h192V576z";
const ECHARTS_EXIT_FULLSCREEN_ICON = "path://M320 192h128v64H384v128h-64V192zm256 0h64v192H448v-64h128V192zM320 576h64v128h64v64H320V576zm256 64h64v128H512v-64h64V640z";

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

interface FullscreenEnabledElement extends HTMLElement {
  webkitRequestFullscreen?: () => Promise<void> | void;
  mozRequestFullScreen?: () => Promise<void> | void;
  msRequestFullscreen?: () => Promise<void> | void;
}

interface FullscreenEnabledDocument extends Document {
  webkitExitFullscreen?: () => Promise<void> | void;
  mozCancelFullScreen?: () => Promise<void> | void;
  msExitFullscreen?: () => Promise<void> | void;
  webkitFullscreenElement?: Element | null;
  mozFullScreenElement?: Element | null;
  msFullscreenElement?: Element | null;
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

function skipQuotedString(source: string, start: number) {
  const quote = source[start];
  let index = start + 1;
  while (index < source.length) {
    if (source[index] === "\\") {
      index += 2;
      continue;
    }
    if (source[index] === quote) {
      return index + 1;
    }
    index += 1;
  }
  return -1;
}

function skipComment(source: string, start: number) {
  if (source[start + 1] === "/") {
    let index = start + 2;
    while (index < source.length && source[index] !== "\n") {
      index += 1;
    }
    return index;
  }
  if (source[start + 1] === "*") {
    const end = source.indexOf("*/", start + 2);
    return end === -1 ? -1 : end + 2;
  }
  return start + 1;
}

function findFunctionLiteralEnd(source: string, start: number) {
  let index = start + "function".length;
  let parenDepth = 0;
  while (index < source.length) {
    const char = source[index];
    if (char === "\"" || char === "'" || char === "`") {
      index = skipQuotedString(source, index);
      if (index === -1) {
        return -1;
      }
      continue;
    }
    if (char === "/" && (source[index + 1] === "/" || source[index + 1] === "*")) {
      index = skipComment(source, index);
      if (index === -1) {
        return -1;
      }
      continue;
    }
    if (char === "(") {
      parenDepth += 1;
    } else if (char === ")") {
      parenDepth = Math.max(0, parenDepth - 1);
    } else if (char === "{" && parenDepth === 0) {
      let braceDepth = 1;
      index += 1;
      while (index < source.length) {
        const bodyChar = source[index];
        if (bodyChar === "\"" || bodyChar === "'" || bodyChar === "`") {
          index = skipQuotedString(source, index);
          if (index === -1) {
            return -1;
          }
          continue;
        }
        if (bodyChar === "/" && (source[index + 1] === "/" || source[index + 1] === "*")) {
          index = skipComment(source, index);
          if (index === -1) {
            return -1;
          }
          continue;
        }
        if (bodyChar === "{") {
          braceDepth += 1;
        } else if (bodyChar === "}") {
          braceDepth -= 1;
          if (braceDepth === 0) {
            return index + 1;
          }
        }
        index += 1;
      }
      return -1;
    }
    index += 1;
  }
  return -1;
}

function replaceFunctionLiterals(source: string) {
  const functions = new Map<string, string>();
  let index = 0;
  let normalized = "";

  while (index < source.length) {
    const char = source[index];
    if (char === "\"" || char === "'" || char === "`") {
      const end = skipQuotedString(source, index);
      if (end === -1) {
        return null;
      }
      normalized += source.slice(index, end);
      index = end;
      continue;
    }
    if (
      source.startsWith("function", index)
      && !/[A-Za-z0-9_$]/.test(source[index - 1] || "")
      && !/[A-Za-z0-9_$]/.test(source[index + "function".length] || "")
    ) {
      const end = findFunctionLiteralEnd(source, index);
      if (end === -1) {
        return null;
      }
      const token = `${ECHARTS_FUNCTION_TOKEN_PREFIX}${functions.size}`;
      functions.set(token, source.slice(index, end));
      normalized += JSON.stringify(token);
      index = end;
      continue;
    }
    normalized += char;
    index += 1;
  }

  return { normalized, functions };
}

function decodeQuotedString(raw: string) {
  const quote = raw[0];
  const inner = raw.slice(1, -1);
  if (quote === "\"") {
    return JSON.parse(raw) as string;
  }
  let decoded = "";
  for (let index = 0; index < inner.length; index += 1) {
    const char = inner[index];
    if (char !== "\\") {
      decoded += char;
      continue;
    }
    index += 1;
    const escaped = inner[index];
    if (escaped === undefined) {
      break;
    }
    if (escaped === "'" || escaped === "\"" || escaped === "\\") {
      decoded += escaped;
    } else if (escaped === "n") {
      decoded += "\n";
    } else if (escaped === "r") {
      decoded += "\r";
    } else if (escaped === "t") {
      decoded += "\t";
    } else {
      decoded += escaped;
    }
  }
  return decoded;
}

function splitTopLevelConcats(expression: string) {
  const parts: string[] = [];
  let current = "";
  let index = 0;
  let parenDepth = 0;

  while (index < expression.length) {
    const char = expression[index];
    if (char === "\"" || char === "'") {
      const end = skipQuotedString(expression, index);
      if (end === -1) {
        return null;
      }
      current += expression.slice(index, end);
      index = end;
      continue;
    }
    if (char === "(") {
      parenDepth += 1;
    } else if (char === ")") {
      parenDepth = Math.max(0, parenDepth - 1);
    } else if (char === "+" && parenDepth === 0) {
      parts.push(current.trim());
      current = "";
      index += 1;
      continue;
    }
    current += char;
    index += 1;
  }

  if (current.trim()) {
    parts.push(current.trim());
  }
  return parts;
}

function getPathValue(input: unknown, path: string[]) {
  let current = input as Record<string, unknown> | null | undefined;
  for (const segment of path) {
    if (current == null || (typeof current !== "object" && typeof current !== "function")) {
      return "";
    }
    current = current[segment] as Record<string, unknown> | null | undefined;
  }
  return current ?? "";
}

function compileLiteralOrPath(expression: string) {
  const trimmed = expression.trim();
  if (!trimmed) {
    return null;
  }
  if (
    (trimmed.startsWith("\"") && trimmed.endsWith("\""))
    || (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    const value = decodeQuotedString(trimmed);
    return () => value;
  }
  if (/^-?\d+(?:\.\d+)?$/.test(trimmed)) {
    const value = Number(trimmed);
    return () => value;
  }
  if (trimmed === "true") {
    return () => true;
  }
  if (trimmed === "false") {
    return () => false;
  }
  if (trimmed === "null") {
    return () => null;
  }
  if (/^params(?:\.[A-Za-z_$][\w$]*)+$/.test(trimmed)) {
    const path = trimmed.split(".").slice(1);
    return (params: unknown) => getPathValue(params, path);
  }
  return null;
}

function compileConcatenationExpression(expression: string) {
  const parts = splitTopLevelConcats(expression);
  if (!parts?.length) {
    return null;
  }
  const compiled = parts.map((part) => compileLiteralOrPath(part));
  if (compiled.some((item) => !item)) {
    return null;
  }
  return (params: unknown) =>
    compiled.map((resolver) => String(resolver?.(params) ?? "")).join("");
}

function compileCondition(condition: string) {
  const match = condition.trim().match(/^(.+?)\s*(===|==|!==|!=)\s*(.+)$/s);
  if (!match) {
    return null;
  }
  const [, leftRaw, operator, rightRaw] = match;
  const left = compileLiteralOrPath(leftRaw);
  const right = compileLiteralOrPath(rightRaw);
  if (!left || !right) {
    return null;
  }
  return (params: unknown) => {
    const leftValue = left(params);
    const rightValue = right(params);
    if (operator === "===" || operator === "==") {
      return leftValue === rightValue;
    }
    return leftValue !== rightValue;
  };
}

function compileFormatterFunction(source: string) {
  const functionMatch = source.match(/^function(?:\s+[A-Za-z_$][\w$]*)?\s*\(([\s\S]*?)\)\s*\{([\s\S]*)\}$/);
  if (!functionMatch) {
    return null;
  }
  const [, paramsSignature, body] = functionMatch;
  if (paramsSignature.trim() !== "params") {
    return null;
  }

  const normalizedBody = body.trim();
  const conditionalMatch = normalizedBody.match(
    /^if\s*\(([\s\S]+?)\)\s*\{\s*return\s+([\s\S]+?);\s*\}\s*else\s*\{\s*return\s+([\s\S]+?);\s*\}\s*$/s,
  );
  if (conditionalMatch) {
    const [, conditionRaw, trueExprRaw, falseExprRaw] = conditionalMatch;
    const condition = compileCondition(conditionRaw);
    const whenTrue = compileConcatenationExpression(trueExprRaw) || compileLiteralOrPath(trueExprRaw);
    const whenFalse = compileConcatenationExpression(falseExprRaw) || compileLiteralOrPath(falseExprRaw);
    if (!condition || !whenTrue || !whenFalse) {
      return null;
    }
    return (params: unknown) => String(condition(params) ? whenTrue(params) : whenFalse(params));
  }

  const returnMatch = normalizedBody.match(/^return\s+([\s\S]+?);\s*$/s);
  if (!returnMatch) {
    return null;
  }
  const expression = compileConcatenationExpression(returnMatch[1]) || compileLiteralOrPath(returnMatch[1]);
  if (!expression) {
    return null;
  }
  return (params: unknown) => expression(params);
}

function hydrateFunctionPlaceholders(input: unknown, functions: Map<string, string>): unknown {
  if (typeof input === "string" && functions.has(input)) {
    return compileFormatterFunction(functions.get(input) ?? "") ?? undefined;
  }
  if (Array.isArray(input)) {
    return input.map((item) => hydrateFunctionPlaceholders(item, functions));
  }
  if (!input || typeof input !== "object") {
    return input;
  }
  const next: Record<string, unknown> = {};
  Object.entries(input).forEach(([key, value]) => {
    const hydrated = hydrateFunctionPlaceholders(value, functions);
    if (hydrated !== undefined) {
      next[key] = hydrated;
    }
  });
  return next;
}

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
    try {
      if (
        trimmedChart.startsWith("{")
        && trimmedChart.endsWith("}")
        && !/\b(?:window|document|globalThis|self|top|parent|frames|fetch|XMLHttpRequest|WebSocket|Worker|SharedWorker|import|export|eval|Function|constructor|prototype|__proto__|localStorage|sessionStorage|navigator|location|history|alert|confirm|prompt|setTimeout|setInterval|requestAnimationFrame|new)\b/.test(trimmedChart)
      ) {
        const factory = new Function(`
          "use strict";
          const window = undefined;
          const document = undefined;
          const globalThis = undefined;
          const self = undefined;
          const top = undefined;
          const parent = undefined;
          const frames = undefined;
          const fetch = undefined;
          const XMLHttpRequest = undefined;
          const WebSocket = undefined;
          const Worker = undefined;
          const SharedWorker = undefined;
          const importScripts = undefined;
          const localStorage = undefined;
          const sessionStorage = undefined;
          const navigator = undefined;
          const location = undefined;
          const history = undefined;
          const alert = undefined;
          const confirm = undefined;
          const prompt = undefined;
          const eval = undefined;
          const Function = undefined;
          const setTimeout = undefined;
          const setInterval = undefined;
          const requestAnimationFrame = undefined;
          return (${trimmedChart});
        `);
        const config = factory();
        if (config && typeof config === "object") {
          echartsRenderCache.set(trimmedChart, config);
          return config;
        }
      }
    } catch (objectLiteralError) {
      console.error("Failed to parse ECharts object literal:", objectLiteralError);
    }

    const functionLiterals = replaceFunctionLiterals(trimmedChart);
    if (!functionLiterals) {
      console.error("Failed to parse ECharts config:", e);
      return null;
    }
    try {
      const parsed = JSON.parse(functionLiterals.normalized);
      const hydrated = hydrateFunctionPlaceholders(parsed, functionLiterals.functions);
      echartsRenderCache.set(trimmedChart, hydrated);
      return hydrated;
    } catch (fallbackError) {
      console.error("Failed to parse ECharts config:", fallbackError);
      return null;
    }
  }
}

function normalizeTreeSeriesData(data: unknown) {
  if (Array.isArray(data)) {
    return data;
  }
  if (data && typeof data === "object") {
    return [data];
  }
  return [];
}

function normalizeShorthandEChartsOption(config: Record<string, any> | null) {
  if (!config || typeof config !== "object" || Array.isArray(config)) {
    return config;
  }
  if (Array.isArray(config.series) && config.series.length) {
    return config;
  }

  const shorthandType = typeof config.type === "string" ? config.type.trim() : "";
  if (!shorthandType) {
    return config;
  }

  const optionLevelKeys = new Set([
    "title",
    "tooltip",
    "legend",
    "toolbox",
    "grid",
    "xAxis",
    "yAxis",
    "dataset",
    "graphic",
    "aria",
    "color",
    "backgroundColor",
    "textStyle",
    "animation",
    "animationThreshold",
    "animationDuration",
    "animationEasing",
    "animationDelay",
    "animationDurationUpdate",
    "animationEasingUpdate",
    "animationDelayUpdate",
    "__mockStream",
  ]);

  const option: Record<string, any> = {};
  const series: Record<string, any> = { type: shorthandType };

  Object.entries(config).forEach(([key, value]) => {
    if (key === "type") {
      return;
    }
    if (optionLevelKeys.has(key)) {
      option[key] = value;
      return;
    }
    series[key] = value;
  });

  if (shorthandType === "tree") {
    series.data = normalizeTreeSeriesData(series.data);
    option.tooltip = option.tooltip || { trigger: "item", triggerOn: "mousemove" };
  }

  option.series = [series];
  return option;
}

function cloneChartConfig<T>(config: T): T {
  if (typeof config === "function") {
    return config;
  }
  if (!config || typeof config !== "object") {
    return config;
  }
  if (Array.isArray(config)) {
    return config.map((item) => cloneChartConfig(item)) as T;
  }
  const cloned = {} as Record<string, unknown>;
  Object.entries(config as Record<string, unknown>).forEach(([key, value]) => {
    cloned[key] = cloneChartConfig(value);
  });
  return cloned as T;
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

function getFullscreenElement(doc: FullscreenEnabledDocument) {
  return doc.fullscreenElement
    || doc.webkitFullscreenElement
    || doc.mozFullScreenElement
    || doc.msFullscreenElement
    || null;
}

async function requestElementFullscreen(element: FullscreenEnabledElement) {
  if (element.requestFullscreen) {
    await element.requestFullscreen();
    return;
  }
  if (element.webkitRequestFullscreen) {
    await element.webkitRequestFullscreen();
    return;
  }
  if (element.mozRequestFullScreen) {
    await element.mozRequestFullScreen();
    return;
  }
  if (element.msRequestFullscreen) {
    await element.msRequestFullscreen();
  }
}

async function exitDocumentFullscreen(doc: FullscreenEnabledDocument) {
  if (doc.exitFullscreen) {
    await doc.exitFullscreen();
    return;
  }
  if (doc.webkitExitFullscreen) {
    await doc.webkitExitFullscreen();
    return;
  }
  if (doc.mozCancelFullScreen) {
    await doc.mozCancelFullScreen();
    return;
  }
  if (doc.msExitFullscreen) {
    await doc.msExitFullscreen();
  }
}

function enhanceToolbox(
  option: Record<string, any> | null,
  isFullscreen: boolean,
  toggleFullscreen: () => void,
) {
  if (!option) {
    return option;
  }
  const nextOption = cloneChartConfig(option);
  const existingToolbox = nextOption.toolbox && typeof nextOption.toolbox === "object"
    ? nextOption.toolbox
    : {};
  const existingFeatures = existingToolbox.feature && typeof existingToolbox.feature === "object"
    ? existingToolbox.feature
    : {};

  nextOption.toolbox = {
    show: true,
    right: 2,
    top: 2,
    itemSize: 16,
    iconStyle: {
      borderColor: "#64748b",
    },
    emphasis: {
      iconStyle: {
        borderColor: "#2563eb",
      },
    },
    ...existingToolbox,
    feature: {
      saveAsImage: { show: true, ...(existingFeatures.saveAsImage || {}) },
      restore: { show: true, ...(existingFeatures.restore || {}) },
      ...existingFeatures,
      [ECHARTS_FULLSCREEN_FEATURE]: {
        show: true,
        title: isFullscreen ? "退出全屏" : "全屏",
        icon: isFullscreen ? ECHARTS_EXIT_FULLSCREEN_ICON : ECHARTS_FULLSCREEN_ICON,
        onclick: toggleFullscreen,
        ...(existingFeatures[ECHARTS_FULLSCREEN_FEATURE] || {}),
      },
    },
  };

  return nextOption;
}

export function EChartsBlock({ chart, style }: EChartsBlockProps) {
  const [error, setError] = useState("");
  const [playbackTick, setPlaybackTick] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<ReactECharts | null>(null);
  const parsedConfig = useMemo(() => {
    const config = parseEChartsConfig(chart);
    if (!config && chart.trim()) {
      setError("Invalid ECharts configuration");
      return null;
    }
    setError("");
    return normalizeShorthandEChartsOption(config);
  }, [chart]);
  const { option: baseOption, mockStream } = useMemo(
    () => stripRuntimeMeta(parsedConfig),
    [parsedConfig],
  );
  const option = useMemo(
    () => applyMockStreamPlayback(baseOption, mockStream, playbackTick),
    [baseOption, mockStream, playbackTick],
  );
  const optionWithToolbox = useMemo(
    () => enhanceToolbox(option, isFullscreen, () => {
      const container = containerRef.current as FullscreenEnabledElement | null;
      if (!container) {
        return;
      }
      const doc = document as FullscreenEnabledDocument;
      const active = getFullscreenElement(doc);
      if (active && container.contains(active)) {
        void exitDocumentFullscreen(doc);
        return;
      }
      void requestElementFullscreen(container);
    }),
    [isFullscreen, option],
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

  useEffect(() => {
    const handleFullscreenChange = () => {
      const doc = document as FullscreenEnabledDocument;
      const active = getFullscreenElement(doc);
      const container = containerRef.current;
      const nextFullscreen = Boolean(active && container && (active === container || container.contains(active)));
      setIsFullscreen(nextFullscreen);
      window.setTimeout(() => {
        chartRef.current?.getEchartsInstance().resize();
      }, 0);
    };

    document.addEventListener("fullscreenchange", handleFullscreenChange);
    document.addEventListener("webkitfullscreenchange", handleFullscreenChange);
    document.addEventListener("mozfullscreenchange", handleFullscreenChange);
    document.addEventListener("MSFullscreenChange", handleFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
      document.removeEventListener("webkitfullscreenchange", handleFullscreenChange);
      document.removeEventListener("mozfullscreenchange", handleFullscreenChange);
      document.removeEventListener("MSFullscreenChange", handleFullscreenChange);
    };
  }, []);

  useEffect(() => {
    chartRef.current?.getEchartsInstance().resize();
  }, [isFullscreen]);

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
      ref={containerRef}
      style={{
        width: "100%",
        minHeight: isFullscreen ? "100vh" : 360,
        height: isFullscreen ? "100vh" : "auto",
        background:
          "linear-gradient(180deg, rgba(248, 250, 252, 0.96) 0%, rgba(255, 255, 255, 0.98) 100%)",
        borderRadius: 16,
        padding: isFullscreen ? 20 : 12,
        border: "1px solid rgba(148, 163, 184, 0.18)",
        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.7), 0 8px 24px rgba(15, 23, 42, 0.05)",
        overflow: "hidden",
        ...style,
      }}
    >
      <ReactECharts
        ref={chartRef}
        echarts={echarts}
        option={optionWithToolbox}
        style={{ height: isFullscreen ? "calc(100vh - 40px)" : "100%", width: "100%", minHeight: 360 }}
        opts={{ renderer: "canvas" }}
        notMerge={true}
        lazyUpdate={true}
        theme="light"
      />
    </div>
  );
}
