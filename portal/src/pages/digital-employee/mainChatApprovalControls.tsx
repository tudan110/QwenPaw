import { useEffect, useId, useRef, useState } from "react";
import {
  APPROVAL_LEVELS,
  approvalRemainingSeconds,
  type MainChatApproval,
  type MainChatApprovalLevel,
} from "./mainChatApproval";
import type { useMainChatApprovals } from "./useMainChatApproval";
import "./mainChatApproval.css";

export function MainChatApprovalModeSelector({
  level,
  onChange,
  disabled,
  error,
}: {
  level: MainChatApprovalLevel;
  onChange: (level: MainChatApprovalLevel) => void;
  disabled: boolean;
  error: string;
}) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const selected = APPROVAL_LEVELS.find((item) => item.value === level) || APPROVAL_LEVELS[0];

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (event.target instanceof Node && !container.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    if (menu.current) {
      const boundary = container.current?.closest(".chat-main, .portal-home-stage")?.getBoundingClientRect();
      const left = Math.max(12, (boundary?.left || 0) + 8);
      const right = Math.min(window.innerWidth - 12, boundary ? boundary.right - 8 : window.innerWidth - 12);
      menu.current.style.width = `${Math.min(310, right - left)}px`;
      const rect = menu.current.getBoundingClientRect();
      const offset = rect.left < left ? left - rect.left : rect.right > right ? right - rect.right : 0;
      menu.current.style.transform = `translateX(${offset}px)`;
    }
    container.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  useEffect(() => {
    setOpen(false);
  }, [disabled]);

  return (
    <div className="main-chat-approval-mode" ref={container}>
      <button
        ref={trigger}
        type="button"
        className={`main-chat-approval-mode-trigger${level === "OFF" ? " unprotected" : ""}`}
        aria-label={`工具执行安全：${selected.label}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        title={error || (disabled ? "本轮执行结束后可切换模式" : "仅影响当前主聊天，不修改智能体默认配置")}
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        <i className="fas fa-shield-halved" aria-hidden="true" />
        <span>{selected.label}</span>
        <i className="fas fa-chevron-down" aria-hidden="true" />
      </button>
      {open ? (
        <div
          ref={menu}
          className="main-chat-approval-mode-menu"
          role="menu"
          id={menuId}
          aria-label="工具执行安全"
          onKeyDown={(event) => {
            const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button"));
            const index = buttons.findIndex((button) => button === document.activeElement);
            const move = event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
            if (move || event.key === "Home" || event.key === "End") {
              event.preventDefault();
              const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
                : (index + move + buttons.length) % buttons.length;
              buttons[next]?.focus();
            }
            if (event.key === "Escape") {
              event.preventDefault();
              setOpen(false);
              trigger.current?.focus();
            }
            if (event.key === "Tab") setOpen(false);
          }}
        >
          <div className="main-chat-approval-mode-caption">当前会话 · 下次发送生效</div>
          {APPROVAL_LEVELS.map((item) => (
            <button
              type="button"
              key={item.value || "inherit"}
              role="menuitemradio"
              aria-checked={item.value === level}
              className={item.value === level ? "selected" : ""}
              onClick={() => {
                onChange(item.value);
                setOpen(false);
                trigger.current?.focus();
              }}
            >
              <span>
                <strong>{item.label}</strong>
                <small>{item.description}</small>
              </span>
              {item.value === level ? <i className="fas fa-check" aria-hidden="true" /> : null}
            </button>
          ))}
        </div>
      ) : null}
      {error && !open ? <span className="main-chat-approval-storage-error" role="status">{error}</span> : null}
    </div>
  );
}

const SEVERITY_LABELS: Record<string, string> = {
  info: "提示", low: "低风险", medium: "中风险", high: "高风险", critical: "严重风险",
};

const SOURCE_LABELS: Record<string, string> = {
  builtin: "内置",
  "STRICT mode": "严格模式",
  "No rule hit": "未匹配规则",
  builtin_rules: "内置规则",
  user_rules: "用户规则",
  sensitive_paths: "敏感路径",
  detection_rules: "风险检测",
  shell_evasion_checks: "命令规避检测",
  shell_danger_keywords: "危险命令检测",
  sandbox: "沙箱",
  fallback: "默认策略",
};

type ApprovalControls = ReturnType<typeof useMainChatApprovals>;

function ApprovalCard({
  approval,
  controls,
}: {
  approval: MainChatApproval;
  controls: ApprovalControls;
}) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const remaining = approvalRemainingSeconds(approval, now);
  const expired = remaining <= 0;
  const busy = controls.busy[approval.request_id];
  const canceling = Object.values(controls.busy).includes("cancel");
  const severity = approval.severity.toLowerCase();
  const source = approval.tool_source || "";
  const generalized = approval.is_generalized && Boolean(approval.similar_target);
  const subAgent = approval.session_id !== approval.root_session_id;
  const run = (action: "exact" | "similar" | "deny" | "cancel") => {
    void controls.act(approval, action);
  };

  return (
    <article className="main-chat-approval-card" aria-label={`${approval.tool_display_name || approval.tool_name} 安全审批`}>
      <header>
        <div className="main-chat-approval-heading">
          <i className="fas fa-shield-halved" aria-hidden="true" />
          <strong>等待安全审批</strong>
          <span className={`main-chat-approval-severity ${severity}`}>
            {SEVERITY_LABELS[severity] || approval.severity}
          </span>
        </div>
        <span className="main-chat-approval-countdown">
          <i className="far fa-clock" aria-hidden="true" />
          {expired ? "已超时" : `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, "0")}`}
        </span>
      </header>
      <div className="main-chat-approval-meta">
        <code>{approval.tool_display_name || approval.tool_name}</code>
        <span>来源：{SOURCE_LABELS[source] || source || "工具防护"}</span>
        <span>风险项：{approval.findings_count}</span>
        {subAgent ? <span>子智能体：{approval.agent_id}</span> : null}
      </div>
      <p className="main-chat-approval-summary">{approval.result_summary || "此工具调用需要您确认后才能继续。"}</p>
      {approval.exact_target ? (
        <div className="main-chat-approval-target">
          <span>精确目标</span><code>{approval.exact_target}</code>
        </div>
      ) : null}
      {generalized ? (
        <div className="main-chat-approval-target">
          <span>通用范围</span><code>{approval.similar_target}</code>
        </div>
      ) : null}
      <p className="main-chat-approval-hint">
        {expired
          ? "审批已超时，本次操作未获批准。"
          : generalized
            ? "批准精确目标不会扩大范围；授权可能在本会话内复用，严格模式仍逐次审批。"
            : "批准后继续执行；拒绝则不执行本次工具调用。"}
      </p>
      <footer>
        <button type="button" className="main-chat-approval-button quiet" disabled={Boolean(busy) || canceling} onClick={() => run("cancel")}>
          {busy === "cancel" ? "正在取消…" : "取消任务"}
        </button>
        <div className="main-chat-approval-decisions">
          <button type="button" className="main-chat-approval-button deny" disabled={expired || Boolean(busy) || canceling} onClick={() => run("deny")}>
            {busy === "deny" ? "正在拒绝…" : "拒绝"}
          </button>
          <button type="button" className={`main-chat-approval-button ${generalized ? "" : "primary"}`} disabled={expired || Boolean(busy) || canceling} onClick={() => run("exact")}>
            {busy === "exact" ? "正在批准…" : generalized ? "批准精确目标" : "批准"}
          </button>
          {generalized ? (
            <button type="button" className="main-chat-approval-button primary" disabled={expired || Boolean(busy) || canceling} onClick={() => run("similar")}>
              {busy === "similar" ? "正在批准…" : "批准通用规则"}
            </button>
          ) : null}
        </div>
      </footer>
    </article>
  );
}

export function MainChatApprovalPanel({ controls }: { controls: ApprovalControls }) {
  if (!controls.items.length && !controls.error && !controls.notice) return null;
  return (
    <section className="main-chat-approval-panel" aria-label="当前会话的安全审批">
      {controls.items.length ? (
        <div className="main-chat-approval-status" role="status">
          <i className="fas fa-pause-circle" aria-hidden="true" />
          有 {controls.items.length} 项操作等待确认，处理后任务将继续。
        </div>
      ) : null}
      {controls.error ? (
        <div className="main-chat-approval-error" role="alert">
          <span>{controls.error}</span>
          <button type="button" onClick={controls.retry}>刷新状态</button>
        </div>
      ) : null}
      {controls.notice ? (
        <div className="main-chat-approval-status" role="status">{controls.notice}</div>
      ) : null}
      {controls.items.map((approval) => (
        <ApprovalCard key={approval.request_id} approval={approval} controls={controls} />
      ))}
    </section>
  );
}
