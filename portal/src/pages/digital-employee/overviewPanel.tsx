import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import ReactECharts from "echarts-for-react";
import DigitalEmployeeAvatar from "../../components/DigitalEmployeeAvatar";
import {
  digitalEmployees,
  getEmployeeById,
  operationsBoardColumns,
  portalStats,
  taskDailyOverviewItems,
} from "../../data/portalData";

type OverviewPanelProps = {
  pageTheme: "light" | "dark";
  onOpenEmployeeChat: (employeeId: string) => void;
};

type AlertDistributionItem = {
  label: string;
  count: number;
  color: string;
  hint: string;
};

type ServiceHealthItem = {
  id: string;
  name: string;
  status: string;
  health: number;
  latency: string;
  owner: string;
};

type AssetMetric = {
  label: string;
  value: string;
  hint: string;
  icon: string;
};

const alertTrendHours = [
  "00:00",
  "02:00",
  "04:00",
  "06:00",
  "08:00",
  "10:00",
  "12:00",
  "14:00",
  "16:00",
  "18:00",
  "20:00",
  "22:00",
];

const alertTrendSeries = {
  total: [8, 7, 6, 9, 14, 18, 16, 12, 10, 11, 9, 7],
  critical: [2, 2, 1, 2, 4, 6, 5, 3, 2, 3, 2, 1],
};

const alertDistribution: AlertDistributionItem[] = [
  { label: "紧急", count: 3, color: "#ef4444", hint: "需 5 分钟内响应" },
  { label: "高危", count: 6, color: "#f97316", hint: "核心链路性能抖动" },
  { label: "一般", count: 11, color: "#f59e0b", hint: "建议当日闭环" },
  { label: "提示", count: 15, color: "#06b6d4", hint: "观测与趋势跟踪" },
];

const serviceHealthItems: ServiceHealthItem[] = [
  {
    id: "svc-core-pay",
    name: "支付核心链路",
    status: "健康",
    health: 99.98,
    latency: "68ms",
    owner: "故障速应",
  },
  {
    id: "svc-billing",
    name: "计费中心",
    status: "关注",
    health: 99.74,
    latency: "112ms",
    owner: "数据洞察员",
  },
  {
    id: "svc-api",
    name: "开放 API 网关",
    status: "健康",
    health: 99.91,
    latency: "74ms",
    owner: "资产管家",
  },
  {
    id: "svc-cmdb",
    name: "CMDB 资产中枢",
    status: "巡检中",
    health: 99.63,
    latency: "95ms",
    owner: "巡弋小卫",
  },
];

const assetMetrics: AssetMetric[] = [
  { label: "纳管资产", value: "12,481", hint: "+168 / 今日", icon: "fa-server" },
  { label: "业务服务", value: "318", hint: "27 条核心链路", icon: "fa-project-diagram" },
  { label: "自动策略", value: "86", hint: "12 条刚刚执行", icon: "fa-bolt" },
];

const priorityRank = {
  P0: 0,
  P1: 1,
  P2: 2,
  P3: 3,
} as const;

const statusRank = {
  running: 0,
  urgent: 0,
  pending: 1,
  completed: 2,
} as const;

function formatNumber(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function parseSuccessRate(value: string) {
  const parsed = Number.parseFloat(value.replace("%", ""));
  return Number.isNaN(parsed) ? 0 : parsed;
}

function getEmployeeStatusMeta(status: string, urgent: boolean) {
  if (urgent) {
    return {
      label: "高优先级",
      tone: "danger",
    } as const;
  }
  if (status === "running") {
    return {
      label: "在线",
      tone: "success",
    } as const;
  }
  if (status === "stopped") {
    return {
      label: "暂停",
      tone: "muted",
    } as const;
  }
  return {
    label: "待命",
    tone: "info",
  } as const;
}

export function OverviewPanel({ pageTheme, onOpenEmployeeChat }: OverviewPanelProps) {
  const isDark = pageTheme === "dark";

  const overviewEmployees = useMemo(
    () =>
      digitalEmployees.map((employee) => ({
        ...employee,
        statusMeta: getEmployeeStatusMeta(employee.status, employee.urgent),
      })),
    [],
  );

  const onlineEmployees = overviewEmployees.filter((employee) => employee.status === "running").length;
  const urgentEmployees = overviewEmployees.filter((employee) => employee.urgent).length;
  const averageSuccess =
    overviewEmployees.reduce((sum, employee) => sum + parseSuccessRate(employee.success), 0) /
    overviewEmployees.length;

  const workorderSummary = useMemo(() => {
    const summary = taskDailyOverviewItems.reduce(
      (result, item) => {
        result.total += 1;
        if (item.status === "completed") {
          result.completed += 1;
        } else if (item.status === "running" || item.status === "urgent") {
          result.running += 1;
        } else {
          result.pending += 1;
        }
        return result;
      },
      { total: 0, completed: 0, running: 0, pending: 0 },
    );

    return {
      ...summary,
      completionRate:
        summary.total > 0 ? Math.round((summary.completed / summary.total) * 100) : 0,
    };
  }, []);

  const workorderQueue = useMemo(
    () =>
      [...taskDailyOverviewItems]
        .sort((left, right) => {
          const leftPriority = priorityRank[left.priority];
          const rightPriority = priorityRank[right.priority];
          if (leftPriority !== rightPriority) {
            return leftPriority - rightPriority;
          }
          const leftStatus = statusRank[left.status];
          const rightStatus = statusRank[right.status];
          if (leftStatus !== rightStatus) {
            return leftStatus - rightStatus;
          }
          return left.timeLabel.localeCompare(right.timeLabel);
        })
        .slice(0, 5),
    [],
  );

  const activeAlerts = alertDistribution
    .slice(0, 3)
    .reduce((sum, item) => sum + item.count, 0);

  const kpiCards = [
    {
      label: "业务可用率",
      value: "99.97%",
      hint: "核心服务 24h 健康度",
      icon: "fa-shield-alt",
      tone: "blue",
    },
    {
      label: "活跃告警",
      value: `${activeAlerts}`,
      hint: "紧急 / 高危 / 一般",
      icon: "fa-exclamation-triangle",
      tone: "red",
    },
    {
      label: "今日工单",
      value: `${workorderSummary.total}`,
      hint: `${workorderSummary.completionRate}% 已闭环`,
      icon: "fa-ticket-alt",
      tone: "amber",
    },
    {
      label: "数字员工在线",
      value: `${onlineEmployees}/${overviewEmployees.length}`,
      hint: `${urgentEmployees} 个高优先级席位`,
      icon: "fa-users-cog",
      tone: "cyan",
    },
    ...assetMetrics.map((metric, index) => ({
      ...metric,
      tone: index === 0 ? "purple" : index === 1 ? "green" : "slate",
    })),
  ];

  const eventFeed = useMemo(
    () =>
      operationsBoardColumns
        .flatMap((column) =>
          column.items.map((item) => ({
            id: item.id,
            title: item.title,
            description: item.description,
            employeeId: item.ownerEmployeeIds[0],
            employeeLabel: item.ownerLabel,
            state: column.title,
            timeLabel: item.statusText || item.timeText,
            tone: item.ownerColor,
          })),
        )
        .slice(0, 6),
    [],
  );

  const chartOption = useMemo<EChartsOption>(
    () => ({
      backgroundColor: "transparent",
      animationDuration: 500,
      grid: {
        left: 12,
        right: 12,
        top: 40,
        bottom: 10,
        containLabel: true,
      },
      legend: {
        top: 0,
        right: 0,
        textStyle: {
          color: isDark ? "#cbd5e1" : "#475569",
          fontSize: 12,
        },
        itemWidth: 10,
        itemHeight: 10,
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: isDark ? "rgba(15, 23, 42, 0.94)" : "rgba(255, 255, 255, 0.96)",
        borderColor: isDark ? "rgba(59, 130, 246, 0.28)" : "rgba(148, 163, 184, 0.24)",
        textStyle: {
          color: isDark ? "#e2e8f0" : "#0f172a",
        },
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: alertTrendHours,
        axisLine: {
          lineStyle: {
            color: isDark ? "rgba(148, 163, 184, 0.18)" : "rgba(148, 163, 184, 0.32)",
          },
        },
        axisLabel: {
          color: isDark ? "#94a3b8" : "#64748b",
          fontSize: 11,
        },
        axisTick: {
          show: false,
        },
      },
      yAxis: {
        type: "value",
        axisLine: {
          show: false,
        },
        splitLine: {
          lineStyle: {
            color: isDark ? "rgba(51, 65, 85, 0.55)" : "rgba(226, 232, 240, 0.88)",
          },
        },
        axisLabel: {
          color: isDark ? "#94a3b8" : "#64748b",
          fontSize: 11,
        },
      },
      series: [
        {
          name: "告警总量",
          type: "line",
          smooth: true,
          data: alertTrendSeries.total,
          symbol: "circle",
          symbolSize: 7,
          lineStyle: {
            width: 3,
            color: "#38bdf8",
          },
          itemStyle: {
            color: "#38bdf8",
          },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(56, 189, 248, 0.34)" },
                { offset: 1, color: "rgba(56, 189, 248, 0.02)" },
              ],
            },
          },
        },
        {
          name: "紧急告警",
          type: "line",
          smooth: true,
          data: alertTrendSeries.critical,
          symbol: "circle",
          symbolSize: 6,
          lineStyle: {
            width: 2,
            color: "#fb7185",
          },
          itemStyle: {
            color: "#fb7185",
          },
        },
      ],
    }),
    [isDark],
  );

  const maxAlertCount = Math.max(...alertDistribution.map((item) => item.count));
  const maxHealth = 100;

  return (
    <div className="portal-overview">
      <section className="overview-hero">
        <div className="overview-hero-copy">
          <div className="overview-kicker">
            <span className="overview-kicker-dot" />
            数字总览
          </div>
          <h3>全局态势感知与数字员工协同调度</h3>
          <p>
            聚合数字员工、工单、告警和业务服务健康度，帮助值班席位在一个视图里完成感知、定位与派发。
          </p>
        </div>
        <div className="overview-hero-badges">
          <div className="overview-hero-badge">
            <strong>{formatNumber(portalStats.tasksToday)}</strong>
            <span>今日自动化动作</span>
          </div>
          <div className="overview-hero-badge">
            <strong>{portalStats.efficiency}%</strong>
            <span>流程自动化效率</span>
          </div>
          <div className="overview-hero-badge">
            <strong>{averageSuccess.toFixed(1)}%</strong>
            <span>数字员工平均成功率</span>
          </div>
        </div>
      </section>

      <section className="overview-kpi-grid">
        {kpiCards.map((card) => (
          <article key={card.label} className={`overview-kpi-card tone-${card.tone}`}>
            <div className="overview-kpi-icon">
              <i className={`fas ${card.icon}`} />
            </div>
            <div className="overview-kpi-content">
              <span>{card.label}</span>
              <strong>{card.value}</strong>
              <em>{card.hint}</em>
            </div>
          </article>
        ))}
      </section>

      <section className="overview-grid">
        <article className="overview-card overview-span-2">
          <header className="overview-card-header">
            <div>
              <h4>数字员工状态</h4>
              <p>在线席位、优先级与能力使用率</p>
            </div>
            <span className="overview-header-tag">实时调度</span>
          </header>
          <div className="overview-employee-grid">
            {overviewEmployees.map((employee) => (
              <button
                key={employee.id}
                type="button"
                className="overview-employee-card"
                onClick={() => onOpenEmployeeChat(employee.id)}
              >
                <div className="overview-employee-card-top">
                  <DigitalEmployeeAvatar employee={employee} className="overview-employee-avatar" />
                  <span className={`overview-status-pill tone-${employee.statusMeta.tone}`}>
                    {employee.statusMeta.label}
                  </span>
                </div>
                <div className="overview-employee-name">{employee.name}</div>
                <div className="overview-employee-desc">{employee.desc}</div>
                <div className="overview-employee-meta">
                  <div>
                    <strong>{formatNumber(employee.tasks)}</strong>
                    <span>累计任务</span>
                  </div>
                  <div>
                    <strong>{employee.success}</strong>
                    <span>成功率</span>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </article>

        <article className="overview-card overview-workorder-card">
          <header className="overview-card-header">
            <div>
              <h4>今日工单</h4>
              <p>以当日待办与运行中任务为主视角</p>
            </div>
            <span className="overview-header-tag subtle">日常闭环</span>
          </header>
          <div className="overview-workorder-summary">
            <div className="overview-workorder-total">
              <strong>{workorderSummary.total}</strong>
              <span>今日总量</span>
            </div>
            <div className="overview-workorder-split">
              <div>
                <strong>{workorderSummary.running}</strong>
                <span>运行中</span>
              </div>
              <div>
                <strong>{workorderSummary.pending}</strong>
                <span>待处理</span>
              </div>
              <div>
                <strong>{workorderSummary.completed}</strong>
                <span>已完成</span>
              </div>
            </div>
          </div>
          <div className="overview-ticket-list">
            {workorderQueue.map((item) => (
              <button
                key={item.id}
                type="button"
                className="overview-ticket-item"
                onClick={() => onOpenEmployeeChat(item.employeeId)}
              >
                <div className="overview-ticket-main">
                  <span className={`overview-priority-tag ${item.priority.toLowerCase()}`}>
                    {item.priority}
                  </span>
                  <div>
                    <strong>{item.title}</strong>
                    <span>
                      {item.employeeLabel || getEmployeeById(item.employeeId)?.name} · {item.timeLabel}
                    </span>
                  </div>
                </div>
                <em>{item.statusText}</em>
              </button>
            ))}
          </div>
        </article>

        <article className="overview-card overview-span-2">
          <header className="overview-card-header">
            <div>
              <h4>24h 告警趋势</h4>
              <p>关注告警总量与紧急告警波峰</p>
            </div>
            <span className="overview-header-tag">近 24 小时</span>
          </header>
          <div className="overview-chart-wrap">
            <ReactECharts
              option={chartOption}
              style={{ height: 280, width: "100%" }}
              notMerge
              lazyUpdate
            />
          </div>
        </article>

        <article className="overview-card">
          <header className="overview-card-header">
            <div>
              <h4>告警分布</h4>
              <p>按告警等级拆分处理压力</p>
            </div>
          </header>
          <div className="overview-distribution-list">
            {alertDistribution.map((item) => (
              <div key={item.label} className="overview-distribution-item">
                <div className="overview-distribution-top">
                  <strong>{item.label}</strong>
                  <span>{item.count}</span>
                </div>
                <div className="overview-distribution-bar">
                  <span
                    style={{
                      width: `${(item.count / maxAlertCount) * 100}%`,
                      background: item.color,
                    }}
                  />
                </div>
                <em>{item.hint}</em>
              </div>
            ))}
          </div>
        </article>

        <article className="overview-card overview-span-2">
          <header className="overview-card-header">
            <div>
              <h4>业务服务健康度</h4>
              <p>按关键服务观察健康分与延迟</p>
            </div>
            <span className="overview-header-tag subtle">服务视角</span>
          </header>
          <div className="overview-service-list">
            {serviceHealthItems.map((service) => (
              <div key={service.id} className="overview-service-item">
                <div className="overview-service-main">
                  <div>
                    <strong>{service.name}</strong>
                    <span>
                      {service.owner} · {service.status}
                    </span>
                  </div>
                  <div className="overview-service-meta">
                    <strong>{service.health.toFixed(2)}%</strong>
                    <span>{service.latency}</span>
                  </div>
                </div>
                <div className="overview-service-bar">
                  <span style={{ width: `${(service.health / maxHealth) * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="overview-card overview-event-card">
          <header className="overview-card-header">
            <div>
              <h4>实时事件流</h4>
              <p>来自当前协同任务与处置动作</p>
            </div>
          </header>
          <div className="overview-event-list">
            {eventFeed.map((event) => (
              <button
                key={event.id}
                type="button"
                className="overview-event-item"
                onClick={() => onOpenEmployeeChat(event.employeeId)}
              >
                <span className="overview-event-dot" style={{ background: event.tone }} />
                <div className="overview-event-content">
                  <strong>{event.title}</strong>
                  <span>{event.description}</span>
                  <em>
                    {event.employeeLabel} · {event.state} · {event.timeLabel}
                  </em>
                </div>
              </button>
            ))}
          </div>
        </article>
      </section>
    </div>
  );
}
