import { Drawer } from "antd";
import { useMemo, useState } from "react";

type FaultScenarioStep = {
  id?: string;
  status?: string;
};

type FaultScenarioLogEntry = {
  stage?: string;
  summary?: string;
};

type FaultScenarioRootCause = {
  type?: string;
  object?: string;
};

type FaultScenarioResult = {
  summary?: string;
  rootCause?: FaultScenarioRootCause;
  steps?: FaultScenarioStep[];
  logEntries?: FaultScenarioLogEntry[];
};

function formatLabel(value?: string, fallback = "待补充") {
  return String(value || fallback);
}

export function FaultScenarioResultCard({ result }: { result: FaultScenarioResult }) {
  const [open, setOpen] = useState(false);
  const rootCause = result?.rootCause || {};
  const steps = useMemo(() => result?.steps || [], [result]);
  const logEntries = useMemo(() => result?.logEntries || [], [result]);

  return (
    <div className="fault-scenario-card">
      <div className="fault-scenario-card-header">
        <div>
          <div className="fault-scenario-eyebrow">结构化诊断结果</div>
          <div className="fault-scenario-summary">{formatLabel(result?.summary, "已完成关联分析")}</div>
        </div>
        <span className="fault-scenario-badge">RCA</span>
      </div>

      <div className="fault-scenario-root-cause">
        <span className="fault-scenario-section-label">根因定位</span>
        <div className="fault-scenario-root-cause-body">
          <strong>{formatLabel(rootCause.type)}</strong>
          <span>{formatLabel(rootCause.object)}</span>
        </div>
      </div>

      <div className="fault-scenario-steps-wrap">
        <span className="fault-scenario-section-label">诊断步骤</span>
        <ul className="fault-scenario-steps">
          {steps.length ? (
            steps.map((step, index) => (
              <li
                key={`${step.id || "step"}-${index}`}
                className={`fault-scenario-step ${step.status || "pending"}`}
              >
                <span className="fault-scenario-step-id">{formatLabel(step.id, `step-${index + 1}`)}</span>
                <span className="fault-scenario-step-status">{formatLabel(step.status, "pending")}</span>
              </li>
            ))
          ) : (
            <li className="fault-scenario-step empty">
              <span className="fault-scenario-step-id">暂无步骤</span>
              <span className="fault-scenario-step-status">pending</span>
            </li>
          )}
        </ul>
      </div>

      <div className="fault-scenario-actions">
        <button
          type="button"
          className="alarm-workorder-action primary"
          onClick={() => setOpen(true)}
        >
          查看诊断日志
        </button>
        <button
          type="button"
          className="alarm-workorder-action fault-scenario-action-muted"
          disabled
          title="故障处置能力待接入"
        >
          故障处置
        </button>
      </div>

      <Drawer
        title="诊断日志"
        open={open}
        onClose={() => setOpen(false)}
        width={440}
        rootClassName="fault-scenario-log-drawer"
      >
        <div className="fault-scenario-log-list">
          {logEntries.length ? (
            logEntries.map((entry, index) => (
              <div key={`${entry.stage || "log"}-${index}`} className="fault-scenario-log-entry">
                <strong>{formatLabel(entry.stage, `stage-${index + 1}`)}</strong>
                <p>{formatLabel(entry.summary, "暂无阶段摘要")}</p>
              </div>
            ))
          ) : (
            <div className="fault-scenario-log-empty">暂无诊断日志</div>
          )}
        </div>
      </Drawer>
    </div>
  );
}
