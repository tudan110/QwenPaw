import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import {
  digitalEmployees,
  employeeResults,
  employeeWorkflows,
} from "../../data/portalData";
import "../cli-terminal.css";

type EmployeeRecord = (typeof digitalEmployees)[number];
type CliTone = "cmd" | "info" | "success" | "error" | "warn" | "accent" | "banner";
type CliLine = {
  id: string;
  content: string;
  tone: CliTone;
};
type CliOutputEntry = {
  content: string;
  tone?: CliTone;
  delay?: number;
};

const TERMINAL_SHORTCUTS = ["help", "list", "status", "agents", "history", "clear"] as const;

function createCliLine(content: string, tone: CliTone = "info"): CliLine {
  return {
    id: `cli-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    content,
    tone,
  };
}

function resolveEmployee(employees: EmployeeRecord[], rawValue: string | null | undefined) {
  const normalized = String(rawValue || "").trim().toLowerCase();
  if (!normalized) {
    return null;
  }

  return (
    employees.find((employee) => employee.id.toLowerCase() === normalized)
    || employees.find((employee) => employee.name.toLowerCase() === normalized)
    || null
  );
}

function getEmployeeState(employee: EmployeeRecord) {
  if (employee.urgent) {
    return { label: "URGENT", tone: "error" as const };
  }
  if (employee.status === "running") {
    return { label: "ACTIVE", tone: "success" as const };
  }
  return { label: "STANDBY", tone: "warn" as const };
}

function buildLoadBar(percent: number) {
  const bounded = Math.max(0, Math.min(100, percent));
  const filled = Math.round(bounded / 10);
  return `${"█".repeat(filled)}${"░".repeat(10 - filled)}`;
}

function computeEmployeeLoad(employee: EmployeeRecord, index: number) {
  const successSeed = Number.parseFloat(employee.success) || 0;
  return Math.max(34, Math.min(96, Math.round(employee.tasks / 90 + successSeed / 2 + index * 3)));
}

function buildHelpEntries(): CliOutputEntry[] {
  return [
    { content: "" },
    { content: "  ╔══════════════════════════════════════════════════════╗", tone: "accent" },
    { content: "  ║              opsPaw Command Reference               ║", tone: "banner" },
    { content: "  ╠══════════════════════════════════════════════════════╣", tone: "accent" },
    { content: "  ║  help                  Show this help message       ║", tone: "info" },
    { content: "  ║  list                  List all digital employees   ║", tone: "info" },
    { content: "  ║  agents                Show active agent status     ║", tone: "info" },
    { content: "  ║  status                System status overview       ║", tone: "info" },
    { content: "  ║  use <id>              Switch current target        ║", tone: "info" },
    { content: "  ║  open [id]             Open employee chat page      ║", tone: "info" },
    { content: "  ║  ask <question>        Ask current target employee  ║", tone: "info" },
    { content: "  ║  run <id> <command>    Execute on specific employee ║", tone: "info" },
    { content: "  ║  deploy <service>      Simulate deployment          ║", tone: "info" },
    { content: "  ║  scan <target>         Run security scan            ║", tone: "info" },
    { content: "  ║  clear                 Clear the terminal           ║", tone: "info" },
    { content: "  ║  history               Show command history         ║", tone: "info" },
    { content: "  ╚══════════════════════════════════════════════════════╝", tone: "accent" },
    { content: "" },
  ];
}

function buildWelcomeEntries(employee: EmployeeRecord | null): CliLine[] {
  const targetLabel = employee ? `${employee.name} (${employee.id})` : "未指定";
  return [
    createCliLine("Welcome to opsPaw CLI Terminal", "banner"),
    createCliLine("输入 help 查看可用命令，输入 use <id> 切换当前终端目标。", "info"),
    createCliLine(`当前目标：${targetLabel}`, "accent"),
    createCliLine("", "info"),
  ];
}

function buildAskEntries(employee: EmployeeRecord, question: string): CliOutputEntry[] {
  const workflow = employeeWorkflows[employee.id as keyof typeof employeeWorkflows] || [];
  const result = employeeResults[employee.id as keyof typeof employeeResults];
  const quickCommand = employee.quickCommands?.[0];
  const primaryMetric = result?.metrics?.[0];
  const fallbackSummary = employee.capabilities.slice(0, 3).join(" / ");

  return [
    { content: "" },
    { content: `  Routing question to ${employee.name}...`, tone: "warn" },
    { content: `  [32%] ${workflow[0] || "任务解析"}中...`, tone: "warn", delay: 320 },
    { content: `  [71%] ${workflow[1] || "能力匹配"}中...`, tone: "warn", delay: 360 },
    { content: "  [100%] Analysis complete.", tone: "success", delay: 420 },
    { content: "" },
    { content: `  ${employee.name} 已接收问题：${question}`, tone: "accent", delay: 180 },
    {
      content: `  重点能力：${fallbackSummary || employee.desc}`,
      tone: "info",
      delay: 140,
    },
    {
      content: result
        ? `  输出预期：${result.title} · ${result.badge}${primaryMetric ? ` · ${primaryMetric.label}${primaryMetric.value}` : ""}`
        : `  输出预期：${employee.desc}`,
      tone: "success",
      delay: 160,
    },
    ...(employee.status !== "running"
      ? [{ content: "  当前员工处于待机状态，本次结果基于离线模拟输出。", tone: "warn" as const, delay: 140 }]
      : []),
    ...(quickCommand
      ? [{ content: `  继续尝试：${quickCommand}`, tone: "info" as const, delay: 120 }]
      : []),
    { content: "" },
  ];
}

function buildRunEntries(employee: EmployeeRecord, command: string): CliOutputEntry[] {
  const workflow = employeeWorkflows[employee.id as keyof typeof employeeWorkflows] || [];
  const result = employeeResults[employee.id as keyof typeof employeeResults];
  const metrics = (result?.metrics || []).slice(0, 2);

  return [
    { content: "" },
    { content: `  Dispatching "${command}" to ${employee.name}...`, tone: "warn" },
    { content: `  [28%] ${workflow[0] || "任务接收"}中...`, tone: "warn", delay: 320 },
    { content: `  [63%] ${workflow[1] || "执行编排"}中...`, tone: "warn", delay: 360 },
    { content: `  [100%] Task completed by ${employee.name}`, tone: "success", delay: 420 },
    ...(result
      ? [{ content: `  结果摘要：${result.title} · ${result.badge}`, tone: "accent" as const, delay: 180 }]
      : []),
    ...metrics.map((metric, index) => ({
      content: `  ${metric.label}：${metric.value}`,
      tone: (index === 0 ? "success" : "info") as CliTone,
      delay: 120,
    })),
    { content: "" },
  ];
}

export function CliTerminalPanel({
  employees,
  activeEmployeeId,
  onOpenEmployeeChat,
}: {
  employees: EmployeeRecord[];
  activeEmployeeId?: string | null;
  onOpenEmployeeChat: (employeeId: string) => void;
}) {
  const terminalOutputRef = useRef<HTMLDivElement | null>(null);
  const scheduledTimersRef = useRef<number[]>([]);
  const [commandInput, setCommandInput] = useState("");
  const [commandHistory, setCommandHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [activeTargetId, setActiveTargetId] = useState(activeEmployeeId || employees[0]?.id || "");
  const [lines, setLines] = useState<CliLine[]>(() =>
    buildWelcomeEntries(resolveEmployee(employees, activeEmployeeId || employees[0]?.id)),
  );

  const activeTarget = useMemo(
    () => resolveEmployee(employees, activeTargetId) || employees[0] || null,
    [activeTargetId, employees],
  );

  const clearScheduledTimers = useCallback(() => {
    scheduledTimersRef.current.forEach((timerId) => window.clearTimeout(timerId));
    scheduledTimersRef.current = [];
  }, []);

  const appendEntries = useCallback((entries: CliOutputEntry[]) => {
    let elapsed = 0;
    entries.forEach((entry) => {
      elapsed += entry.delay || 0;
      const timerId = window.setTimeout(() => {
        setLines((current) => [...current, createCliLine(entry.content, entry.tone || "info")]);
      }, elapsed);
      scheduledTimersRef.current.push(timerId);
    });
  }, []);

  useEffect(() => () => {
    clearScheduledTimers();
  }, [clearScheduledTimers]);

  useEffect(() => {
    if (activeEmployeeId && resolveEmployee(employees, activeEmployeeId)) {
      setActiveTargetId(activeEmployeeId);
    }
  }, [activeEmployeeId, employees]);

  useEffect(() => {
    terminalOutputRef.current?.scrollTo({
      top: terminalOutputRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [lines]);

  const runCommand = useCallback((rawCommand: string) => {
    const command = rawCommand.trim();
    if (!command) {
      return;
    }

    setCommandHistory((current) => [...current, command]);
    setHistoryIndex(-1);
    setLines((current) => [...current, createCliLine(`opsPaw> ${command}`, "cmd")]);

    const parts = command.split(/\s+/);
    const action = parts[0]?.toLowerCase() || "";

    if (action === "clear") {
      clearScheduledTimers();
      setLines([]);
      return;
    }

    if (action === "help") {
      appendEntries(buildHelpEntries());
      return;
    }

    if (action === "list") {
      appendEntries([
        { content: "" },
        { content: "  Digital Employee Matrix:", tone: "accent" },
        { content: `  ${"-".repeat(54)}`, tone: "info" },
        ...employees.map((employee) => {
          const state = getEmployeeState(employee);
          const marker = activeTarget?.id === employee.id ? "›" : " ";
          return {
            content: ` ${marker} ${employee.id.padEnd(12)} ${employee.name.padEnd(8)} [${state.label}]`,
            tone: state.tone,
          };
        }),
        { content: "" },
      ]);
      return;
    }

    if (action === "status") {
      const running = employees.filter((employee) => employee.status === "running").length;
      const urgent = employees.filter((employee) => employee.urgent).length;
      const stopped = employees.length - running;
      const totalTasks = employees.reduce((sum, employee) => sum + employee.tasks, 0);
      appendEntries([
        { content: "" },
        { content: "  System Status Overview", tone: "accent" },
        { content: `  ${"-".repeat(40)}`, tone: "info" },
        { content: `  Employees Online:  ${running}/${employees.length}`, tone: "success" },
        { content: `  Urgent Alerts:     ${urgent}`, tone: urgent > 0 ? "error" : "success" },
        { content: `  Standby Agents:    ${stopped}`, tone: stopped > 0 ? "warn" : "info" },
        { content: `  Managed Tasks:     ${totalTasks.toLocaleString("zh-CN")}`, tone: "info" },
        { content: `  Current Target:    ${activeTarget?.name || "未指定"}`, tone: "accent" },
        { content: "" },
      ]);
      return;
    }

    if (action === "agents") {
      appendEntries([
        { content: "" },
        { content: "  ┌─ Active Agent Status ─────────────────────┐", tone: "accent" },
        ...employees.map((employee, index) => {
          const load = computeEmployeeLoad(employee, index);
          const state = getEmployeeState(employee);
          return {
            content: `  │ ${employee.name.padEnd(10)} [${state.label}]  Load: ${buildLoadBar(load)}  ${String(load).padStart(2)}%`,
            tone: state.tone,
            delay: index === 0 ? 120 : 90,
          };
        }),
        { content: "  └──────────────────────────────────────────┘", tone: "accent", delay: 120 },
        { content: "" },
      ]);
      return;
    }

    if (action === "use") {
      const employee = resolveEmployee(employees, parts[1]);
      if (!employee) {
        appendEntries([{ content: '  Error: usage: use <employee_id>', tone: "error" }]);
        return;
      }

      setActiveTargetId(employee.id);
      appendEntries([
        { content: `  Current target switched to ${employee.name} (${employee.id})`, tone: "success" },
        { content: '  输入 "open" 可直接进入该数字员工对话。', tone: "info" },
        { content: "" },
      ]);
      return;
    }

    if (action === "open") {
      const employee = resolveEmployee(employees, parts[1]) || activeTarget;
      if (!employee) {
        appendEntries([{ content: '  Error: usage: open <employee_id>', tone: "error" }]);
        return;
      }

      appendEntries([{ content: `  Opening ${employee.name} chat...`, tone: "warn" }]);
      const timerId = window.setTimeout(() => {
        onOpenEmployeeChat(employee.id);
      }, 420);
      scheduledTimersRef.current.push(timerId);
      return;
    }

    if (action === "ask") {
      const question = parts.slice(1).join(" ");
      if (!question) {
        appendEntries([{ content: '  Error: usage: ask <question>', tone: "error" }]);
        return;
      }
      if (!activeTarget) {
        appendEntries([{ content: "  Error: no active target employee.", tone: "error" }]);
        return;
      }

      appendEntries(buildAskEntries(activeTarget, question));
      return;
    }

    if (action === "run") {
      const employee = resolveEmployee(employees, parts[1]);
      const subCommand = parts.slice(2).join(" ");
      if (!employee || !subCommand) {
        appendEntries([{ content: '  Error: usage: run <employee_id> <command>', tone: "error" }]);
        return;
      }

      appendEntries(buildRunEntries(employee, subCommand));
      return;
    }

    if (action === "deploy") {
      const service = parts.slice(1).join(" ") || "default-service";
      appendEntries([
        { content: "" },
        { content: `  Deploying "${service}"...`, tone: "warn" },
        { content: "  [1/5] Pulling latest image...", tone: "info", delay: 320 },
        { content: "  [2/5] Running pre-deploy checks...", tone: "info", delay: 420 },
        { content: "  [3/5] Rolling update started...", tone: "warn", delay: 520 },
        { content: "  [4/5] Health check passing...", tone: "success", delay: 520 },
        { content: `  [5/5] Deploy complete! Service "${service}" is live.`, tone: "success", delay: 520 },
        { content: "" },
      ]);
      return;
    }

    if (action === "scan") {
      const target = parts.slice(1).join(" ") || "all-services";
      appendEntries([
        { content: "" },
        { content: `  Scanning "${target}"...`, tone: "warn" },
        { content: `  [${buildLoadBar(18)}] 18%`, tone: "info", delay: 260 },
        { content: `  [${buildLoadBar(43)}] 43%`, tone: "info", delay: 320 },
        { content: `  [${buildLoadBar(67)}] 67%`, tone: "info", delay: 320 },
        { content: `  [${buildLoadBar(88)}] 88%`, tone: "info", delay: 320 },
        { content: `  [${buildLoadBar(100)}] 100%`, tone: "success", delay: 360 },
        { content: "" },
        { content: "  Scan Results:", tone: "accent" },
        { content: "  ✓ No critical vulnerabilities found", tone: "success" },
        { content: "  ! 2 medium-risk items detected", tone: "warn" },
        { content: "  ✓ SSL certificates valid", tone: "success" },
        { content: "  ✓ Ports scan clean", tone: "success" },
        { content: "" },
      ]);
      return;
    }

    if (action === "history") {
      appendEntries([
        { content: "" },
        { content: "  Command History:", tone: "accent" },
        ...(commandHistory.length
          ? commandHistory.map((item, index) => ({
            content: `  ${index + 1}. ${item}`,
            tone: "info" as const,
          }))
          : [{ content: "  暂无历史命令。", tone: "info" as const }]),
        { content: "" },
      ]);
      return;
    }

    appendEntries([
      {
        content: `  Unknown command: "${action}". Type "help" for available commands.`,
        tone: "error",
      },
    ]);
  }, [activeTarget, appendEntries, clearScheduledTimers, commandHistory, employees, onOpenEmployeeChat]);

  const handleSubmitCommand = useCallback(() => {
    const nextCommand = commandInput;
    setCommandInput("");
    runCommand(nextCommand);
  }, [commandInput, runCommand]);

  const handleInputKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      handleSubmitCommand();
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!commandHistory.length) {
        return;
      }
      const nextIndex =
        historyIndex < 0 ? commandHistory.length - 1 : Math.max(0, historyIndex - 1);
      setHistoryIndex(nextIndex);
      setCommandInput(commandHistory[nextIndex] || "");
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!commandHistory.length) {
        return;
      }
      if (historyIndex < 0) {
        return;
      }
      const nextIndex = historyIndex + 1;
      if (nextIndex >= commandHistory.length) {
        setHistoryIndex(-1);
        setCommandInput("");
        return;
      }
      setHistoryIndex(nextIndex);
      setCommandInput(commandHistory[nextIndex] || "");
    }
  };

  return (
    <div className="cli-terminal-panel">
      <div className="portal-model-page-header">
        <div className="portal-model-page-title">
          CLI终端 <small>命令行交互界面</small>
        </div>
        <div className="portal-model-page-actions">
          <span className="cli-terminal-target-badge">
            当前目标：{activeTarget?.name || "未指定"}
          </span>
          {activeTarget ? (
            <button
              type="button"
              className="portal-model-btn"
              onClick={() => onOpenEmployeeChat(activeTarget.id)}
            >
              打开对话
            </button>
          ) : null}
        </div>
      </div>

      <div className="cli-terminal-content">
        <div className="cli-terminal-shortcuts">
          {TERMINAL_SHORTCUTS.map((shortcut) => (
            <button
              key={shortcut}
              type="button"
              className="cli-terminal-shortcut"
              onClick={() => runCommand(shortcut)}
            >
              {shortcut}
            </button>
          ))}
        </div>

        <div className="cli-terminal-shell">
          <div className="cli-terminal-topbar">
            <div className="cli-terminal-dots" aria-hidden="true">
              <span className="red" />
              <span className="yellow" />
              <span className="green" />
            </div>
            <div className="cli-terminal-topbar-title">opsPaw CLI / Portal</div>
            <div className="cli-terminal-topbar-target">{activeTarget?.id || "default"}</div>
          </div>

          <div ref={terminalOutputRef} className="cli-output" role="log" aria-live="polite">
            {lines.map((line) => (
              <div key={line.id} className={`cli-line cli-line-${line.tone}`}>
                {line.content}
              </div>
            ))}
          </div>

          <div className="cli-input-row">
            <span className="cli-prompt">opsPaw&gt;</span>
            <input
              className="cli-input"
              value={commandInput}
              placeholder='输入命令...（输入 "help" 查看帮助）'
              onChange={(event) => {
                setCommandInput(event.target.value);
                setHistoryIndex(-1);
              }}
              onKeyDown={handleInputKeyDown}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
