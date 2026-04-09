import { useCallback, useEffect, useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import * as echarts from "echarts";
import {
  tokenUsageApi,
  type TokenUsageStats,
  type TokenUsageSummary,
} from "../../api/tokenUsage";

type TokenUsagePanelProps = {
  pageTheme: "light" | "dark";
  currentEmployeeName: string;
};

type TokenUsageModelRow = TokenUsageStats & {
  key: string;
  total_tokens: number;
};

type TokenUsageDateRow = TokenUsageStats & {
  key: string;
  date: string;
  total_tokens: number;
};

type TokenUsageProviderRow = TokenUsageStats & {
  key: string;
  total_tokens: number;
};

function formatDateInput(date: Date) {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function buildDefaultDateRange() {
  const end = new Date();
  const start = new Date(end);
  start.setDate(end.getDate() - 30);
  return {
    startDate: formatDateInput(start),
    endDate: formatDateInput(end),
  };
}

function normalizeDateRange(startDate: string, endDate: string) {
  if (!startDate || !endDate || startDate <= endDate) {
    return { startDate, endDate };
  }
  return { startDate: endDate, endDate: startDate };
}

function formatCompact(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    notation: "compact",
    maximumFractionDigits: value >= 100000 ? 1 : 0,
  }).format(value);
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatDateLabel(value: string) {
  if (!value) {
    return "--";
  }
  const [, month = "", day = ""] = value.split("-");
  return `${month}/${day}`;
}

function totalTokens(stats: TokenUsageStats) {
  return stats.prompt_tokens + stats.completion_tokens;
}

export function TokenUsagePanel({
  pageTheme,
  currentEmployeeName,
}: TokenUsagePanelProps) {
  const defaultRange = useMemo(() => buildDefaultDateRange(), []);
  const [startDate, setStartDate] = useState(defaultRange.startDate);
  const [endDate, setEndDate] = useState(defaultRange.endDate);
  const [summary, setSummary] = useState<TokenUsageSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadTokenUsage = useCallback(async (rangeStartDate: string, rangeEndDate: string) => {
    const range = normalizeDateRange(rangeStartDate, rangeEndDate);
    setLoading(true);
    setError("");

    try {
      const nextSummary = await tokenUsageApi.getTokenUsage({
        start_date: range.startDate,
        end_date: range.endDate,
      });
      setSummary(nextSummary);
      setStartDate(range.startDate);
      setEndDate(range.endDate);
    } catch (fetchError) {
      console.error("Failed to load token usage summary:", fetchError);
      setError(fetchError instanceof Error ? fetchError.message : "Token 统计加载失败");
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchTokenUsage = useCallback(
    async () => loadTokenUsage(startDate, endDate),
    [endDate, loadTokenUsage, startDate],
  );

  const resetTokenUsage = useCallback(async () => {
    await loadTokenUsage(defaultRange.startDate, defaultRange.endDate);
  }, [defaultRange.endDate, defaultRange.startDate, loadTokenUsage]);

  useEffect(() => {
    void loadTokenUsage(defaultRange.startDate, defaultRange.endDate);
  }, [defaultRange.endDate, defaultRange.startDate, loadTokenUsage]);

  const byModelRows = useMemo<TokenUsageModelRow[]>(() => {
    return Object.entries(summary?.by_model || {})
      .map(([key, stats]) => ({
        ...stats,
        key,
        total_tokens: totalTokens(stats),
      }))
      .sort((left, right) => right.total_tokens - left.total_tokens || right.call_count - left.call_count);
  }, [summary?.by_model]);

  const byDateRowsAsc = useMemo<TokenUsageDateRow[]>(() => {
    return Object.entries(summary?.by_date || {})
      .map(([date, stats]) => ({
        ...stats,
        key: date,
        date,
        total_tokens: totalTokens(stats),
      }))
      .sort((left, right) => left.date.localeCompare(right.date));
  }, [summary?.by_date]);

  const byDateRowsDesc = useMemo(() => [...byDateRowsAsc].reverse(), [byDateRowsAsc]);

  const byProviderRows = useMemo<TokenUsageProviderRow[]>(() => {
    return Object.entries(summary?.by_provider || {})
      .map(([providerId, stats]) => ({
        ...stats,
        key: providerId || "default",
        total_tokens: totalTokens(stats),
      }))
      .sort((left, right) => right.total_tokens - left.total_tokens || right.call_count - left.call_count);
  }, [summary?.by_provider]);

  const totalTokenCount = useMemo(
    () => (summary?.total_prompt_tokens || 0) + (summary?.total_completion_tokens || 0),
    [summary?.total_completion_tokens, summary?.total_prompt_tokens],
  );

  const statCards = useMemo(
    () => [
      {
        label: "输入 Token",
        value: formatCompact(summary?.total_prompt_tokens || 0),
        meta: `${formatNumber(summary?.total_prompt_tokens || 0)} tokens`,
        accent: "primary",
        icon: "fa-arrow-right-to-bracket",
      },
      {
        label: "输出 Token",
        value: formatCompact(summary?.total_completion_tokens || 0),
        meta: `${formatNumber(summary?.total_completion_tokens || 0)} tokens`,
        accent: "purple",
        icon: "fa-arrow-right-from-bracket",
      },
      {
        label: "总调用次数",
        value: formatCompact(summary?.total_calls || 0),
        meta: `${byProviderRows.length} 个模型源`,
        accent: "green",
        icon: "fa-bolt",
      },
      {
        label: "总 Token",
        value: formatCompact(totalTokenCount),
        meta: `${byModelRows.length} 个模型`,
        accent: "cyan",
        icon: "fa-chart-column",
      },
    ],
    [byModelRows.length, byProviderRows.length, summary?.total_calls, summary?.total_completion_tokens, summary?.total_prompt_tokens, totalTokenCount],
  );

  const chartOption = useMemo(() => {
    const isDark = pageTheme === "dark";
    return {
      backgroundColor: "transparent",
      animationDuration: 400,
      tooltip: {
        trigger: "axis",
        backgroundColor: isDark ? "rgba(20, 27, 45, 0.96)" : "rgba(255, 255, 255, 0.96)",
        borderColor: "rgba(79, 110, 247, 0.25)",
        textStyle: {
          color: isDark ? "#e2e8f0" : "#1e293b",
          fontSize: 12,
        },
      },
      legend: {
        data: ["输入 Token", "输出 Token"],
        bottom: 0,
        textStyle: {
          color: isDark ? "#94a3b8" : "#64748b",
        },
      },
      grid: {
        left: 48,
        right: 18,
        top: 18,
        bottom: 42,
      },
      xAxis: {
        type: "category",
        data: byDateRowsAsc.map((row) => formatDateLabel(row.date)),
        axisLine: {
          lineStyle: {
            color: "rgba(79, 110, 247, 0.15)",
          },
        },
        axisLabel: {
          color: isDark ? "#94a3b8" : "#94a3b8",
          fontSize: 11,
        },
      },
      yAxis: {
        type: "value",
        axisLine: { show: false },
        splitLine: {
          lineStyle: {
            color: isDark ? "rgba(79, 110, 247, 0.1)" : "rgba(79, 110, 247, 0.08)",
          },
        },
        axisLabel: {
          color: isDark ? "#94a3b8" : "#94a3b8",
          formatter: (value: number) => formatCompact(value),
        },
      },
      series: [
        {
          name: "输入 Token",
          type: "bar",
          stack: "total",
          barWidth: 22,
          itemStyle: {
            borderRadius: [0, 0, 0, 0],
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "#4f6ef7" },
              { offset: 1, color: "rgba(79, 110, 247, 0.45)" },
            ]),
          },
          data: byDateRowsAsc.map((row) => row.prompt_tokens),
        },
        {
          name: "输出 Token",
          type: "bar",
          stack: "total",
          barWidth: 22,
          itemStyle: {
            borderRadius: [4, 4, 0, 0],
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "#a78bfa" },
              { offset: 1, color: "rgba(167, 139, 250, 0.42)" },
            ]),
          },
          data: byDateRowsAsc.map((row) => row.completion_tokens),
        },
      ],
    };
  }, [byDateRowsAsc, pageTheme]);

  const hasData = Boolean(summary && summary.total_calls > 0);

  return (
    <div className="token-usage-page">
      <div className="token-usage-static">
        <div className="portal-model-page-header">
          <div className="portal-model-page-title">
            Token统计 <small>资源消耗分析</small>
          </div>
        </div>

        <div className="portal-model-scope-bar token-usage-scope-bar">
          <span>当前数字员工：{currentEmployeeName}</span>
          <span>统计范围：全局模型调用</span>
          <span>统计区间：{startDate} 至 {endDate}</span>
        </div>

        <div className="token-usage-filter-bar">
          <label className="token-usage-filter-field">
            <span>开始日期</span>
            <input
              type="date"
              value={startDate}
              max={endDate || undefined}
              onChange={(event) => setStartDate(event.target.value)}
            />
          </label>
          <label className="token-usage-filter-field">
            <span>结束日期</span>
            <input
              type="date"
              value={endDate}
              min={startDate || undefined}
              onChange={(event) => setEndDate(event.target.value)}
            />
          </label>
          <div className="token-usage-filter-actions">
            <button
              type="button"
              className="portal-model-btn token-usage-filter-action token-usage-filter-action-query"
              disabled={loading || !startDate || !endDate}
              onClick={() => void fetchTokenUsage()}
            >
              <i className={`fas ${loading ? "fa-spinner fa-spin" : "fa-magnifying-glass"}`} />
              查询
            </button>
            <button
              type="button"
              className="portal-model-btn secondary token-usage-filter-action token-usage-filter-action-reset"
              disabled={loading}
              onClick={() => void resetTokenUsage()}
            >
              <i className="fas fa-rotate-left" />
              重置
            </button>
          </div>
        </div>

        {error ? <div className="model-inline-notice error">{error}</div> : null}
      </div>

      <div className="token-usage-scroll">
        {loading && !summary ? (
          <div className="token-usage-empty">
            <i className="fas fa-chart-column" />
            <p>正在加载 Token 统计...</p>
          </div>
        ) : hasData ? (
          <>
            <div className="token-usage-stats-row">
              {statCards.map((item) => (
                <article
                  key={item.label}
                  className={`token-usage-stat-card token-usage-stat-card-${item.accent}`}
                >
                  <div className="token-usage-stat-icon">
                    <i className={`fas ${item.icon}`} />
                  </div>
                  <div className="token-usage-stat-label">{item.label}</div>
                  <div className="token-usage-stat-value">{item.value}</div>
                  <div className="token-usage-stat-meta">{item.meta}</div>
                </article>
              ))}
            </div>

            <section className="token-usage-chart-card">
              <div className="token-usage-card-head">
                <div>
                  <h4>Token 趋势</h4>
                  <p>按日期展示输入 / 输出 token 消耗变化</p>
                </div>
              </div>
              <ReactECharts
                echarts={echarts}
                option={chartOption}
                style={{ height: 320, width: "100%" }}
                opts={{ renderer: "canvas" }}
                notMerge={true}
                lazyUpdate={true}
              />
            </section>

            <div className="token-usage-detail-grid">
              <section className="token-usage-table-card token-usage-table-card-wide">
                <div className="token-usage-card-head">
                  <div>
                    <h4>模型明细</h4>
                    <p>按模型 / 模型源聚合的 token 消耗与调用次数</p>
                  </div>
                </div>
                <div className="token-usage-table-wrap">
                  <table className="token-usage-table">
                    <thead>
                      <tr>
                        <th>模型源</th>
                        <th>模型</th>
                        <th>输入 Token</th>
                        <th>输出 Token</th>
                        <th>总计</th>
                        <th>调用次数</th>
                      </tr>
                    </thead>
                    <tbody>
                      {byModelRows.map((row) => (
                        <tr key={row.key}>
                          <td>{row.provider_id || "默认"}</td>
                          <td>{row.model || row.key}</td>
                          <td>{formatNumber(row.prompt_tokens)}</td>
                          <td>{formatNumber(row.completion_tokens)}</td>
                          <td className="token-usage-emphasis">{formatNumber(row.total_tokens)}</td>
                          <td>{formatNumber(row.call_count)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="token-usage-table-card">
                <div className="token-usage-card-head">
                  <div>
                    <h4>模型源统计</h4>
                    <p>快速查看各模型源的整体消耗</p>
                  </div>
                </div>
                <div className="token-usage-provider-list">
                  {byProviderRows.map((row) => (
                    <div key={row.key} className="token-usage-provider-item">
                      <div>
                        <strong>{row.key || "默认"}</strong>
                        <span>{formatNumber(row.call_count)} 次调用</span>
                      </div>
                      <em>{formatNumber(row.total_tokens)} tokens</em>
                    </div>
                  ))}
                </div>
              </section>

              <section className="token-usage-table-card">
                <div className="token-usage-card-head">
                  <div>
                    <h4>每日明细</h4>
                    <p>用于回溯近一段时间的消耗峰值</p>
                  </div>
                </div>
                <div className="token-usage-table-wrap">
                  <table className="token-usage-table token-usage-table-compact">
                    <thead>
                      <tr>
                        <th>日期</th>
                        <th>总计</th>
                        <th>调用次数</th>
                      </tr>
                    </thead>
                    <tbody>
                      {byDateRowsDesc.map((row) => (
                        <tr key={row.key}>
                          <td>{row.date}</td>
                          <td className="token-usage-emphasis">{formatNumber(row.total_tokens)}</td>
                          <td>{formatNumber(row.call_count)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>
          </>
        ) : (
          <div className="token-usage-empty">
            <i className="fas fa-chart-column" />
            <p>当前时间范围内暂无 Token 统计数据</p>
          </div>
        )}
      </div>
    </div>
  );
}
