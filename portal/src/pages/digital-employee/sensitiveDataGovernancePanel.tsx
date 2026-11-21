import { useEffect, useState } from "react";
import { Alert, Button, Collapse, Skeleton, Tag } from "antd";
import { CheckCircleOutlined, ExperimentOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { readControlled, writeControlled } from "../../api/controlledDocuments";
import "./sensitiveDataGovernance.css";

const endpoint = "/admin/sensitive-data";
const coverageLabels = {
  enforced: ["已接入", "green"],
  partial: ["部分接入", "gold"],
  outside: ["不在本页校验范围", undefined],
} as const;

type GovernanceStatus = {
  categories: { id: string; name: string; group: string; labels: string[]; scope: string }[];
  coverage: { id: string; name: string; status: keyof typeof coverageLabels; detail: string }[];
  approval_seconds: number;
  emergency: boolean;
  security_hold: boolean;
};
type CheckRun = {
  run_id: string;
  completed_at: number;
  samples: { title: string; labels: string[]; preview: string | null }[];
  checks: { key: string; label: string; decision: "allowed" | "denied"; passed: boolean; reason: string; event_id: string }[];
};

const errorText = (error: unknown) => error instanceof Error ? error.message : "请求失败，请重试。";

export function SensitiveDataGovernancePanel() {
  const [status, setStatus] = useState<GovernanceStatus | null>(null);
  const [statusError, setStatusError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState("");
  const [run, setRun] = useState<CheckRun | null>(null);

  useEffect(() => {
    let current = true;
    readControlled<GovernanceStatus>(endpoint).then(
      (data) => { if (current) setStatus(data); },
      (error: unknown) => { if (current) setStatusError(errorText(error)); },
    );
    return () => { current = false; };
  }, [attempt]);

  async function runCheck() {
    setRunning(true);
    setRun(null);
    setRunError("");
    try {
      setRun(await writeControlled<CheckRun>(`${endpoint}/check`));
    } catch (error) {
      setRunError(errorText(error));
    } finally {
      setRunning(false);
    }
  }

  if (statusError) return <Alert showIcon type="warning" title="暂时无法读取治理状态" description={statusError}
    action={<Button size="small" onClick={() => { setStatusError(""); setAttempt((value) => value + 1); }}>重新加载</Button>} />;
  if (!status) return <section className="gov-surface sd-section" aria-label="正在加载敏感数据治理"><Skeleton active paragraph={{ rows: 3 }} /></section>;

  const passed = run?.checks.filter((check) => check.passed).length ?? 0;
  return <div className="gov-flow sd-governance">
    <section className="gov-surface sd-overview" aria-labelledby="sd-categories">
      <div className="sd-banner">
        <span className="sd-banner-icon"><SafetyCertificateOutlined aria-hidden="true" /></span>
        <div><h4 id="sd-categories">敏感分类与最小权限</h4>
          <p>按场景查看已接入的管控。受控资料默认只提供脱敏读取，原文导出另行授权。</p>
        </div>
        <Tag>402-2.5</Tag>
      </div>
      <div className="sd-categories">
        {status.categories.map((category) => <article key={category.id} className="sd-class">
          <span className="gov-eyebrow">{category.group}</span>
          <h5>{category.name}</h5>
          <div className="sd-tags">{category.labels.map((label) => <Tag key={label}>{label}</Tag>)}</div>
          <p>{category.scope}</p>
        </article>)}
      </div>
    </section>

    <section className="gov-surface sd-section" aria-labelledby="sd-coverage">
      <header className="sd-heading"><div><h4 id="sd-coverage">场景覆盖与访问边界</h4>
        <p>受控资料的申请有效期最长 {Math.round(status.approval_seconds / 60)} 分钟。未接入的场景不能以本页作为管控证明。</p></div>
        {status.emergency && <Tag color="red">受控资料已紧急关停</Tag>}
        {status.security_hold && <Tag color="orange">当前账号操作已冻结</Tag>}
      </header>
      <ul className="sd-coverage">
        {status.coverage.map((item) => <li key={item.id}>
          <strong>{item.name}</strong><span><Tag color={coverageLabels[item.status][1]}>{coverageLabels[item.status][0]}</Tag></span>
          <p>{item.detail}</p>
        </li>)}
      </ul>
    </section>

    <section className="gov-surface sd-section" aria-labelledby="sd-check">
      <header className="sd-heading"><div><h4 id="sd-check">分类与授权自检</h4>
        <p>服务端使用固定合成资料运行实际分类、脱敏与授权校验。审批状态仅为隔离样例，不修改真实授权、不下载原文。</p></div>
        <Button type="primary" icon={<ExperimentOutlined />} loading={running} onClick={() => void runCheck()}>运行合成样例自检</Button>
      </header>
      {runError && <Alert showIcon type="error" title="自检未取得结果" description={runError} />}
      {!run && !runError && <div className="sd-empty" role="status">{running ? "正在运行分类与授权校验…" : "运行后将展示分类标签、脱敏预览、允许与拒绝结果，以及对应的服务端审计编号。"}</div>}
      {run && <div className="sd-results">
        <div className="sd-run-meta" role="status">
          <Tag color={passed === run.checks.length ? "green" : "red"} icon={passed === run.checks.length ? <CheckCircleOutlined /> : undefined}>{passed} / {run.checks.length} 项符合预期</Tag>
          <Tag>合成样例</Tag>
          <span>{new Date(run.completed_at * 1000).toLocaleString("zh-CN")}</span>
          <span>审计批次 <code>{run.run_id}</code></span>
        </div>
        <div className="sd-samples">
          {run.samples.map((sample) => <article key={sample.title}>
            <h5>{sample.title}</h5>
            <div className="sd-tags">{sample.labels.map((label) => <Tag color="blue" key={label}>{label}</Tag>)}</div>
            {sample.preview ? <pre aria-label={`${sample.title}脱敏预览`}>{sample.preview}</pre> : <p>自检未通过，未返回预览。</p>}
          </article>)}
        </div>
        <ul className="sd-checks" aria-label="授权校验结果">
          {run.checks.map((check) => <li key={check.key}>
            <div><strong>{check.label}</strong><Tag color={!check.passed ? "red" : check.decision === "allowed" ? "green" : "gold"}>
              {check.decision === "allowed" ? "允许" : "拒绝"}{!check.passed && " · 不符合预期"}
            </Tag></div>
            <p>{check.reason}</p>
          </li>)}
        </ul>
        <Collapse size="small" items={[{ key: "events", label: "查看各项审计编号", children: <ul className="sd-event-list">
          {run.checks.map((check) => <li key={check.key}>{check.label} <code>{check.event_id}</code></li>)}
        </ul> }]} />
      </div>}
    </section>
  </div>;
}
