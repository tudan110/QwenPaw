import { useEffect, useMemo, useState } from "react";
import DigitalEmployeeAvatar from "../../components/DigitalEmployeeAvatar";
import { getEmployeeById, taskDailyOverviewItems, taskViewItems } from "../../data/portalData";
import type { TaskViewItem } from "../../types/portal";

type TaskFilter = "all" | "running" | "completed" | "pending";

const TASK_FILTER_OPTIONS: Array<{ id: TaskFilter; label: string }> = [
  { id: "all", label: "全部" },
  { id: "running", label: "运行中" },
  { id: "completed", label: "已完成" },
  { id: "pending", label: "待处理" },
];

const TASK_PAGE_SIZE = 8;

function getGreetingLabel(): string {
  const hour = new Date().getHours();
  if (hour >= 18) {
    return "晚上好";
  }
  if (hour >= 12) {
    return "下午好";
  }
  return "早上好";
}

function getDateLabel(): string {
  const now = new Date();
  const weekdays = ["日", "一", "二", "三", "四", "五", "六"];
  return `${now.getFullYear()}年${now.getMonth() + 1}月${now.getDate()}日 星期${weekdays[now.getDay()]}`;
}

function matchesFilter(item: TaskViewItem, filter: TaskFilter): boolean {
  if (filter === "all") {
    return true;
  }
  if (filter === "running") {
    return item.status === "running" || item.status === "urgent";
  }
  if (filter === "completed") {
    return item.status === "completed";
  }
  return item.status === "pending";
}

type TaskViewPanelProps = {
  onOpenEmployeeChat: (employeeId: string) => void;
};

export function TaskViewPanel({ onOpenEmployeeChat }: TaskViewPanelProps) {
  const [taskFilter, setTaskFilter] = useState<TaskFilter>("all");
  const [taskPage, setTaskPage] = useState(1);
  const [actionNotice, setActionNotice] = useState<string | null>(null);

  const dailyOverviewTasks = useMemo(() => taskDailyOverviewItems, []);
  const pendingApprovalCount = useMemo(
    () =>
      dailyOverviewTasks.filter(
        (item) => item.actionKind === "approve" || item.actionKind === "confirm",
      ).length,
    [dailyOverviewTasks],
  );
  const urgentCount = useMemo(
    () => taskViewItems.filter((item) => item.status === "urgent").length,
    [],
  );
  const completedCount = useMemo(
    () => dailyOverviewTasks.filter((item) => item.status === "completed").length,
    [dailyOverviewTasks],
  );
  const filteredTasks = useMemo(
    () => taskViewItems.filter((item) => matchesFilter(item, taskFilter)),
    [taskFilter],
  );
  const totalPages = Math.max(1, Math.ceil(filteredTasks.length / TASK_PAGE_SIZE));
  const pageTasks = useMemo(() => {
    const start = (taskPage - 1) * TASK_PAGE_SIZE;
    return filteredTasks.slice(start, start + TASK_PAGE_SIZE);
  }, [filteredTasks, taskPage]);
  const pageNumbers = useMemo(
    () => Array.from({ length: totalPages }, (_, index) => index + 1),
    [totalPages],
  );

  useEffect(() => {
    setTaskPage(1);
  }, [taskFilter]);

  useEffect(() => {
    if (taskPage > totalPages) {
      setTaskPage(totalPages);
    }
  }, [taskPage, totalPages]);

  useEffect(() => {
    if (!actionNotice) {
      return undefined;
    }
    const timeoutId = window.setTimeout(() => setActionNotice(null), 2800);
    return () => window.clearTimeout(timeoutId);
  }, [actionNotice]);

  const handleTaskAction = (item: TaskViewItem) => {
    if (item.actionKind === "view" || item.actionKind === "detail") {
      onOpenEmployeeChat(item.employeeId);
      return;
    }
    if (item.actionKind === "confirm") {
      setActionNotice(`已确认「${item.title}」，${getEmployeeById(item.employeeId).name} 将继续跟进。`);
      return;
    }
    if (item.actionKind === "approve") {
      setActionNotice(`审批已通过，「${item.title}」已交给 ${getEmployeeById(item.employeeId).name} 执行。`);
    }
  };

  return (
    <div className="task-view-page">
      <div className="task-view-header">
        <h3 className="task-view-title">
          任务列表
          <small>数字员工自动编排任务</small>
        </h3>
      </div>

      <section className="task-view-daily-board">
        <div className="task-view-greeting">
          <div className="task-view-greeting-avatar" aria-hidden="true">
            <i className="fas fa-robot" />
          </div>
          <div className="task-view-greeting-copy">
            <div className="task-view-greeting-heading">
              <div>
                <h4>
                  {getGreetingLabel()}，张工！我是您的工作小助手
                </h4>
                <p>今日将由数字员工团队协助您完成以下工作任务，请放心交给我们。</p>
              </div>
              <span>{getDateLabel()}</span>
            </div>
          </div>
        </div>

        <div className="task-view-section-title">今日工作待办总览</div>

        <div className="task-view-stats">
          <article className="task-view-stat-card">
            <strong>98</strong>
            <span>今日设备健康分</span>
          </article>
          <article className="task-view-stat-card accent-amber">
            <strong>{pendingApprovalCount}</strong>
            <span>待审批</span>
          </article>
          <article className="task-view-stat-card accent-red">
            <strong>{urgentCount}</strong>
            <span>待处置告警</span>
          </article>
          <article className="task-view-stat-card accent-green">
            <strong>{completedCount}</strong>
            <span>今日已完成</span>
          </article>
        </div>

        <div className="task-view-daily-table-shell">
          <table className="task-view-daily-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>任务内容</th>
                <th>执行员工</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {dailyOverviewTasks.map((item) => {
                const employee = getEmployeeById(item.employeeId);
                return (
                  <tr key={item.id}>
                    <td className="task-view-time">{item.timeLabel}</td>
                    <td>{item.title}</td>
                    <td>
                      <div className="task-view-employee">
                        <DigitalEmployeeAvatar
                          employee={employee}
                          className="task-view-employee-avatar"
                        />
                        <span>{item.employeeLabel || employee.name}</span>
                      </div>
                    </td>
                    <td>
                      <span
                        className={`task-view-status-badge ${item.statusVariant || item.status}`}
                      >
                        {item.statusText}
                      </span>
                    </td>
                    <td>
                      {item.actionKind === "none" ? (
                        <span className="task-view-action-dash">—</span>
                      ) : (
                        <button
                          type="button"
                          className={
                            item.actionKind === "approve" || item.actionKind === "confirm"
                              ? "task-view-action-btn primary"
                              : "task-view-action-btn"
                          }
                          onClick={() => handleTaskAction(item)}
                        >
                          {item.actionLabel}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <div className="task-view-filter-bar">
        {TASK_FILTER_OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            className={taskFilter === option.id ? "task-view-filter-chip active" : "task-view-filter-chip"}
            onClick={() => setTaskFilter(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>

      {actionNotice ? <div className="task-view-notice">{actionNotice}</div> : null}

      <section className="task-view-table-shell">
        <div className="task-view-table-scroll">
          <table className="task-view-table">
            <thead>
              <tr>
                <th>任务ID</th>
                <th>任务名称</th>
                <th>执行数字员工</th>
                <th>触发来源</th>
                <th>状态</th>
                <th>优先级</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              {pageTasks.map((item) => {
                const employee = getEmployeeById(item.employeeId);
                return (
                  <tr key={item.id}>
                    <td className="task-view-id">{item.id}</td>
                    <td>
                      <div className="task-view-name">
                        <span>{item.title}</span>
                        {item.auto ? <span className="task-view-auto-tag">自动</span> : null}
                      </div>
                    </td>
                    <td>
                      <div className="task-view-employee compact">
                        <DigitalEmployeeAvatar
                          employee={employee}
                          className="task-view-employee-avatar"
                        />
                        <span>{item.employeeLabel || employee.name}</span>
                      </div>
                    </td>
                    <td className="task-view-source">{item.source}</td>
                    <td>
                      <span
                        className={`task-view-status-badge ${item.statusVariant || item.status}`}
                      >
                        {item.statusText}
                      </span>
                    </td>
                    <td>
                      <span className={`task-view-priority ${item.priority.toLowerCase()}`}>
                        {item.priority}
                      </span>
                    </td>
                    <td className="task-view-source">{item.scheduledAt}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="task-view-pagination">
          <span className="task-view-pagination-info">
            共 {filteredTasks.length} 条，第 {taskPage}/{totalPages} 页
          </span>
          <div className="task-view-pagination-buttons">
            <button
              type="button"
              className="task-view-page-btn"
              disabled={taskPage <= 1}
              onClick={() => setTaskPage((value) => Math.max(1, value - 1))}
            >
              <i className="fas fa-angle-left" />
            </button>
            {pageNumbers.map((page) => (
              <button
                key={page}
                type="button"
                className={page === taskPage ? "task-view-page-btn active" : "task-view-page-btn"}
                onClick={() => setTaskPage(page)}
              >
                {page}
              </button>
            ))}
            <button
              type="button"
              className="task-view-page-btn"
              disabled={taskPage >= totalPages}
              onClick={() => setTaskPage((value) => Math.min(totalPages, value + 1))}
            >
              <i className="fas fa-angle-right" />
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
