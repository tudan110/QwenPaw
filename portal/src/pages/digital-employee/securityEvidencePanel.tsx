import { AlarmExportSettings } from "./alarmExportControls";
import { useEffect, useState, type ReactNode } from "react";
import { Alert, ConfigProvider, DatePicker, Input, Select, Table, Tabs, theme } from "antd";
import { Link } from "react-router-dom";
import {
  securityEvidenceApi, SecurityEvidenceError,
  type AuditPage, type AuditRecord, type MCPAdmissionCheck, type ProtectionEvidence,
} from "../../api/securityEvidence";
import { auditCsvCell } from "./evidenceDisplay";
import { SecurityBoundaryOverview } from "./securityBoundaryOverview";
import { PortalIncidentPanel } from "./portalIncidentPanel";
import { CriticalAuditPanel } from "./criticalAuditPanel";
import "./securityEvidencePanel.css";

const ON_OFF = (enabled: boolean) => enabled ? "开启" : "关闭";
const CLOCK = (value: string | number) => new Date(value).toLocaleString("zh-CN", { hour12: false });
const ERROR_TEXT = (error: unknown) => error instanceof SecurityEvidenceError
  ? error.message : "无法读取安全取证数据，请稍后重试。";
const DECISIONS = { allow: "允许", deny: "拒绝", ask: "请求确认", sandbox_fallback: "沙箱回退" };
const PAGE_SIZE = 50;

const ADMISSION_TARGETS = {
  registered: "已登记端点",
  default_host: "内置回环主机",
  unregistered: "未知端点（规则校验）",
} as const;

const ADMISSION_UNAVAILABLE = {
  guards_disabled: "生产保护未开启，未执行准入校验。",
  invalid_policy: "精确白名单配置无效，未执行准入校验。",
  no_exact_policy: "后端未返回主机规则校验结果。请核对部署版本和准入策略。",
} as const;

function EvidenceBadge({ tone = "neutral", children }: {
  tone?: "success" | "warning" | "danger" | "neutral";
  children: ReactNode;
}) {
  return <span className={`security-evidence-badge ${tone}`}>{children}</span>;
}

const ICON_PATHS = {
  shield: "M12 22s7-3.5 7-9V5l-7-3-7 3v8c0 5.5 7 9 7 9z M9 12l2 2 4-4",
  lock: "M7 10V7a5 5 0 0 1 10 0v3 M6 10h12a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z M12 14v3",
  scan: "M3 9V5a2 2 0 0 1 2-2h4 M15 3h4a2 2 0 0 1 2 2v4 M21 15v4a2 2 0 0 1-2 2h-4 M9 21H5a2 2 0 0 1-2-2v-4 M3 12h18",
  audit: "M6 3h12a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z M8 8h8 M8 12h8 M8 16h5",
  refresh: "M20 7v5h-5 M19.5 12a7.5 7.5 0 1 0-2 5.1",
} as const;

function EvidenceIcon({ name, size = 18 }: { name: keyof typeof ICON_PATHS; size?: number }) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    <path d={ICON_PATHS[name]} />
  </svg>;
}

function EvidenceHeading({ id, title, description, icon, actions }: {
  id: string;
  title: string;
  description: string;
  icon: keyof typeof ICON_PATHS;
  actions?: ReactNode;
}) {
  return <div className="security-evidence-heading">
    <span className="settings-tab-icon" aria-hidden="true"><EvidenceIcon name={icon} /></span>
    <div className="security-evidence-heading-copy">
      <h4 id={id}>{title}</h4>
      <p>{description}</p>
    </div>
    {actions && <div className="security-evidence-actions">{actions}</div>}
  </div>;
}

function MCPAdmissionMonitor({ boundary, result, loading, error, onRefresh }: {
  boundary?: ProtectionEvidence["mcp_boundary"];
  result?: MCPAdmissionCheck;
  loading: boolean;
  error: string;
  onRefresh: () => void;
}) {
  const mode = boundary?.endpoint_policy;
  const hostMode = result?.state === "host_policy" || (!result && boundary?.production_guards && !mode);
  const rows = result?.cases ?? [];
  const unknown = rows.find((row) => row.case === "unregistered");
  const unavailable = result && result.state !== "ready" && result.state !== "host_policy"
    ? ADMISSION_UNAVAILABLE[result.state] : undefined;

  return <section className="security-evidence-card" aria-labelledby="mcp-admission-title">
    <EvidenceHeading id="mcp-admission-title" title="外部服务与端点管控" icon="shield"
      description="查看 MCP 远程端点的准入策略，以及后端对未知端点的规则判定。"
      actions={<>
        <Link className="portal-model-btn secondary" to="/mcp">MCP 服务与工具权限</Link>
        <button type="button" className="portal-model-btn" disabled={loading} onClick={onRefresh}>
          <EvidenceIcon name="refresh" size={15} />
          {loading ? "正在校验…" : "刷新并校验"}
        </button>
      </>} />
    <dl className="security-evidence-metrics">
      <div>
        <dt>生产保护</dt>
        <dd>{boundary ? <EvidenceBadge tone={boundary.production_guards ? "success" : "warning"}>{ON_OFF(boundary.production_guards)}</EvidenceBadge> : "—"}</dd>
      </div>
      <div>
        <dt>远程准入策略</dt>
        <dd>{!boundary ? "—" : mode === "invalid" ? <EvidenceBadge tone="danger">白名单配置无效</EvidenceBadge>
          : mode === "exact" ? `精确端点白名单${boundary.declared_endpoint_count == null ? "" : ` · ${boundary.declared_endpoint_count} 项`}`
          : `主机白名单 · ${boundary.declared_host_count} 个显式主机`}</dd>
      </div>
      <div>
        <dt>未知端点校验</dt>
        <dd>{unknown ? <EvidenceBadge tone={unknown.decision === "deny" ? "success" : "danger"}>
          {unknown.decision === "deny" ? "规则拒绝" : "规则未拒绝"}
        </EvidenceBadge> : loading ? "校验中" : "未确认"}</dd>
      </div>
    </dl>
    {hostMode && (
      <Alert type="warning" showIcon title="当前仅按主机准入，同一允许主机下的接口路径不逐条核对。" />
    )}
    {error && <Alert type="error" showIcon title={error} />}
    {unavailable && <Alert type="warning" showIcon title={unavailable} />}
    <div className="security-evidence-table-group" aria-busy={loading}>
      <div className="security-evidence-table-head">
        <h5 id="mcp-admission-results">MCP 端点准入校验结果</h5>
        <span role="status">{result ? `校验时间：${CLOCK(result.checked_at)}` : loading ? "正在读取后端判定…" : "未取得校验时间"}</span>
      </div>
      <div className="security-evidence-table-scroll" tabIndex={0} role="region" aria-labelledby="mcp-admission-results">
        <table className="security-evidence-monitor-table" aria-labelledby="mcp-admission-results">
          <thead><tr>
            <th scope="col">检查对象</th><th scope="col">传输方式</th><th scope="col">预期决策</th>
            <th scope="col">后端判定</th><th scope="col">核对结果</th>
          </tr></thead>
          <tbody>{rows.length ? rows.map((row) => (
            <tr key={row.case}>
              <th scope="row">{ADMISSION_TARGETS[row.case]}</th>
              <td>{row.transport === "streamable_http" ? "Streamable HTTP" : row.transport === "sse" ? "SSE" : row.transport}</td>
              <td>{DECISIONS[row.expected]}</td>
              <td><EvidenceBadge tone={row.decision === "deny" ? "danger" : "success"}>{DECISIONS[row.decision]}</EvidenceBadge></td>
              <td><EvidenceBadge tone={row.decision === row.expected ? "success" : "danger"}>
                {row.decision === row.expected ? "符合预期" : "不符合预期"}
              </EvidenceBadge></td>
            </tr>
          )) : <tr><td colSpan={5} className="security-evidence-empty">{loading ? "正在校验准入规则…" : "暂无准入校验结果"}</td></tr>}</tbody>
        </table>
      </div>
      <p className="security-evidence-note">
        {mode === "exact" && "精确模式按传输方式、URL 协议、主机、端口和路径匹配。"}
        校验使用后端准入规则，不读取凭据、不连接 MCP 服务；未知端点使用保留测试地址。表内结果不是实际调用日志。
      </p>
    </div>
  </section>;
}

function ProtectionOverview() {
  const [snapshot, setSnapshot] = useState<ProtectionEvidence>();
  const [admission, setAdmission] = useState<MCPAdmissionCheck>();
  const [snapshotError, setSnapshotError] = useState("");
  const [admissionError, setAdmissionError] = useState("");
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    setLoading(true);
    setChecking(true);
    setSnapshot(undefined);
    setAdmission(undefined);
    setSnapshotError("");
    setAdmissionError("");
    void securityEvidenceApi.protection(signal).then((result) => {
      if (!signal.aborted) setSnapshot(result);
    }).catch((error) => {
      if (!signal.aborted) setSnapshotError(ERROR_TEXT(error));
    }).finally(() => {
      if (!signal.aborted) setLoading(false);
    });
    void securityEvidenceApi.checkMCPAdmission(true, signal).then((result) => {
      if (!signal.aborted) setAdmission(result);
    }).catch((error) => {
      if (!signal.aborted) setAdmissionError(ERROR_TEXT(error));
    }).finally(() => {
      if (!signal.aborted) setChecking(false);
    });
    return () => controller.abort();
  }, [revision]);

  const guard = snapshot?.output_guard;
  return <div className="security-evidence-stack">
    <MCPAdmissionMonitor boundary={snapshot?.mcp_boundary} result={admission} loading={loading || checking}
      error={admissionError} onRefresh={() => setRevision((value) => value + 1)} />
    <section className="security-evidence-card" aria-labelledby="output-guard-title" aria-busy={loading}>
      <EvidenceHeading id="output-guard-title" title="输出脱敏配置" icon="lock"
        description="展示后端解析后的当前配置。各渠道的实际输出脱敏效果需结合业务检查。" />
      {snapshotError && <Alert type="error" showIcon title={snapshotError} />}
      {loading && <p className="security-evidence-note" role="status">正在读取脱敏配置…</p>}
      {guard && <>
        <dl className="security-evidence-metrics">
          <div><dt>输出脱敏</dt><dd><EvidenceBadge tone={guard.active ? "success" : "neutral"}>{ON_OFF(guard.active)}</EvidenceBadge></dd></div>
          <div><dt>脱敏模式</dt><dd>{guard.mode === "mask" ? "掩码" : guard.mode}</dd></div>
          <div><dt>流式脱敏配置</dt><dd>{ON_OFF(guard.mask_streaming)}</dd></div>
          <div><dt>词库来源</dt><dd>{guard.lexicon === "custom" ? "自定义词库" : "内置词库"}</dd></div>
        </dl>
        <div className="security-evidence-rules">
          <h5>脱敏规则配置</h5>
          <ul>{guard.patterns.map((rule) => <li key={rule.id}>
            <code>{rule.id}</code><EvidenceBadge tone={rule.enabled ? "success" : "neutral"}>{ON_OFF(rule.enabled)}</EvidenceBadge>
          </li>)}</ul>
        </div>
        <p className="security-evidence-note">配置读取时间：{CLOCK(snapshot.queried_at)}</p>
      </>}
    </section>
    <section className="security-evidence-card" aria-labelledby="skill-scan-title">
      <EvidenceHeading id="skill-scan-title" title="技能扫描范围" icon="scan"
        description="技能扫描用于导入和审核检查；扫描记录不代表运行时提示注入防护或完整的内容安全覆盖。" />
    </section>
  </div>;
}

const EXECUTION = {
  started: "已开始", success: "成功", error: "失败", denied: "执行被拒绝",
  cancelled: "已取消", returned: "已返回（未声明业务结果）", unconfirmed: "结果未确认",
} as const;

function PolicyAudit({ execution = false }: { execution?: boolean }) {
  const [draft, setDraft] = useState({ agent_id: "", tool_name: "", decision: "" });
  const [times, setTimes] = useState<{ since?: number; until?: number }>({});
  const [query, setQuery] = useState<Record<string, string | number>>({ limit: PAGE_SIZE, offset: 0 });
  const [data, setData] = useState<AuditPage>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setData(undefined);
    setError("");
    void securityEvidenceApi.audit(execution ? { ...query, kind: "tool_execution" } : query, controller.signal).then((result) => {
      if (!controller.signal.aborted) setData(result);
    }).catch((error) => {
      if (!controller.signal.aborted) setError(ERROR_TEXT(error));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [execution, query]);

  const page = Number(query.offset) / PAGE_SIZE + 1;
  const exportPage = () => {
    if (!data?.records.length) return;
    const contextFields = ["ts", "subject", "agent_id", "session_id", "tool_name", "target"] as const;
    const fields = execution ? [...contextFields, "execution_result", "call_id"] as const
      : [...contextFields, "decision", "reason"] as const;
    const rows = [
      ["record_kind", data.record_kind, "execution_result", data.execution_result],
      ["queried_at", data.queried_at, "scope", "current_page", "page", page],
      fields,
      ...data.records.map((record) => fields.map((field) => record[field])),
    ];
    const blob = new Blob(["\uFEFF", rows.map((row) => row.map(auditCsvCell).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${execution ? "tool-execution" : "policy"}-audit-page-${page}.csv`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <section className="security-evidence-card" aria-labelledby="tool-audit-title" aria-busy={loading}>
      <EvidenceHeading id="tool-audit-title" title={execution ? "工具执行记录" : "工具策略决策"}
        icon="audit" description={execution
          ? "通过调用编号关联执行开始与结果。仅有开始记录时，结果尚未确认。"
          : "查看工具调用的允许、拒绝或审批等策略决策。实际执行结果请查看「执行审计」。"}
        actions={<button type="button" className="portal-model-btn secondary" disabled={loading || !data?.records.length}
          onClick={exportPage}>导出当前页</button>} />
      {execution && <p className="security-evidence-note">本地记录不自动清理；长期留存和防篡改需通过独立归档验证。</p>}
      <form className="security-evidence-filters" aria-label="审计记录筛选" onSubmit={(event) => {
        event.preventDefault();
        setQuery({
          ...Object.fromEntries(Object.entries(draft).map(([key, value]) => [key, value.trim()]).filter(([, value]) => value)),
          ...times, offset: 0, limit: PAGE_SIZE,
        });
      }}>
        <Input aria-label="智能体 ID" placeholder="智能体 ID" maxLength={200} value={draft.agent_id}
          onChange={(event) => setDraft({ ...draft, agent_id: event.target.value })} />
        <Input aria-label="工具名称" placeholder="工具名称" maxLength={200} value={draft.tool_name}
          onChange={(event) => setDraft({ ...draft, tool_name: event.target.value })} />
        {!execution && <Select aria-label="策略决策" value={draft.decision}
          options={[{ value: "", label: "全部决策" }, ...Object.entries(DECISIONS).map(([value, label]) => ({ value, label }))]}
          onChange={(decision) => setDraft({ ...draft, decision })} />}
        <DatePicker.RangePicker showTime placeholder={["开始时间", "结束时间"]}
          onChange={(values) => setTimes(values?.[0] && values[1] ? { since: values[0].valueOf(), until: values[1].valueOf() } : {})} />
        <button type="submit" className="portal-model-btn" disabled={loading}>{loading ? "查询中…" : "查询"}</button>
      </form>
      {error && <Alert type="error" showIcon title={error} />}
      {data && <p className="security-evidence-note">数据源：{data.source} · 读取时间：{CLOCK(data.queried_at)} · 共 {data.total} 条</p>}
      {data?.storage_status === "not_created" && <Alert type="info" title="尚无审计数据库。" />}
      {data?.storage_status === "unsupported_schema" && <Alert type="warning" title="现有审计库结构不支持只读展示，数据未迁移。" />}
      <Table<AuditRecord> rowKey="rowid" size="small" loading={loading} dataSource={data?.records ?? []}
        scroll={{ x: 950 }} locale={{ emptyText: error ? "数据未读取" : "没有匹配的审计记录" }}
        pagination={{ current: page, pageSize: PAGE_SIZE, total: Math.min(data?.total ?? 0, 100000 + PAGE_SIZE), showSizeChanger: false,
          onChange: (next) => setQuery((current) => ({ ...current, offset: (next - 1) * PAGE_SIZE })) }}
        columns={[
          { title: "时间", dataIndex: "ts", render: CLOCK },
          { title: "操作主体", dataIndex: "subject", render: (value?: string) => value || "未记录" },
          { title: "智能体 ID", dataIndex: "agent_id" },
          { title: "会话 ID", dataIndex: "session_id" },
          { title: "工具", dataIndex: "tool_name" },
          { title: "目标（脱敏）", dataIndex: "target" },
          ...(execution ? [
            { title: "执行结果", dataIndex: "execution_result", render: (value: keyof typeof EXECUTION) => EXECUTION[value] || "未确认" },
            { title: "调用编号", dataIndex: "call_id" },
          ] : [
            { title: "策略决策", dataIndex: "decision", render: (value: keyof typeof DECISIONS) => <EvidenceBadge tone={value === "allow" ? "success" : value === "deny" ? "danger" : "neutral"}>{DECISIONS[value] || value}</EvidenceBadge> },
            { title: "原因（脱敏）", dataIndex: "reason" },
          ]),
        ]} />
    </section>
  );
}

export function PortalSecurityEvidence({ pageTheme, canManageAi = false }: {
  pageTheme: "light" | "dark";
  canManageAi?: boolean;
}) {
  const [tab, setTab] = useState("boundaries");
  return <ConfigProvider theme={{
    algorithm: pageTheme === "dark" ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: { colorPrimary: pageTheme === "dark" ? "#79aaff" : "#2563eb", borderRadius: 8 },
  }}>
    <div className="security-evidence">
      <header className="security-evidence-page-heading">
        <h3>安全与审计</h3>
        <p>查看安全边界、异常中止处置和工具调用审计。</p>
      </header>
      <Tabs activeKey={tab} onChange={setTab} destroyOnHidden items={[
        { key: "boundaries", label: "安全边界总览", children: <SecurityBoundaryOverview openProtection={() => setTab("protection")} /> },
        { key: "protection", label: "防护概览", children: <ProtectionOverview /> },
        ...(canManageAi ? [{ key: "alarm-export", label: "导出管控", children: <AlarmExportSettings /> }] : []),
        { key: "incidents", label: "异常中止", children: <PortalIncidentPanel /> },
        { key: "critical-audit", label: "关键活动审计", children: <CriticalAuditPanel /> },
        { key: "audit", label: "策略审计", children: <PolicyAudit /> },
        { key: "execution", label: "执行审计", children: <PolicyAudit execution /> },
      ]} />
    </div>
  </ConfigProvider>;
}
