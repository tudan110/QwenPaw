import { useEffect, useState } from "react";
import { Alert, Button, DatePicker, Descriptions, Input, Select, Space, Table, Tabs, Tag } from "antd";
import { Link } from "react-router-dom";
import {
  securityEvidenceApi, SecurityEvidenceError,
  type AuditPage, type AuditRecord, type ProtectionEvidence, type RedactionCheck,
} from "../../api/securityEvidence";
import { auditCsvCell } from "./evidenceDisplay";

const ON_OFF = (enabled: boolean) => enabled ? "开启" : "关闭";
const CLOCK = (value: string | number) => new Date(value).toLocaleString();
const ERROR_TEXT = (error: unknown) => error instanceof SecurityEvidenceError
  ? error.message : "无法读取安全取证数据，请稍后重试。";
const DECISIONS = { allow: "允许", deny: "拒绝", ask: "请求确认", sandbox_fallback: "沙箱回退" };
const PAGE_SIZE = 50;

function ProtectionOverview() {
  const [snapshot, setSnapshot] = useState<ProtectionEvidence>();
  const [check, setCheck] = useState<RedactionCheck>();
  const [error, setError] = useState("");
  const [checkError, setCheckError] = useState("");
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setSnapshot(undefined);
    setCheck(undefined);
    setError("");
    setCheckError("");
    void securityEvidenceApi.protection(controller.signal).then((result) => {
      if (!controller.signal.aborted) setSnapshot(result);
    }).catch((error) => {
      if (!controller.signal.aborted) setError(ERROR_TEXT(error));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [revision]);

  const runCheck = async () => {
    setChecking(true);
    setCheck(undefined);
    setCheckError("");
    try {
      setCheck(await securityEvidenceApi.checkRedaction());
    } catch (error) {
      setCheckError(ERROR_TEXT(error));
    } finally {
      setChecking(false);
    }
  };

  const guard = snapshot?.output_guard;
  return (
    <div className="portal-model-shell">
      <section className="settings-section" aria-label="输出脱敏配置">
        <Space wrap>
          <h4>输出脱敏配置</h4>
          <Button size="small" loading={loading} disabled={checking} onClick={() => setRevision((value) => value + 1)}>刷新快照</Button>
          {snapshot && <span>读取时间：{CLOCK(snapshot.queried_at)}</span>}
        </Space>
        <p>本页展示后端解析后的配置，各渠道实际生效情况需通过业务测试核对。</p>
        {error && <Alert type="error" showIcon message={error} />}
        {guard && <>
          <Descriptions size="small" bordered column={{ xs: 1, sm: 2 }} items={[
            { key: "active", label: "输出脱敏", children: ON_OFF(guard.active) },
            { key: "mode", label: "模式", children: guard.mode },
            { key: "streaming", label: "流式脱敏配置", children: ON_OFF(guard.mask_streaming) },
            { key: "lexicon", label: "词库来源", children: guard.lexicon === "custom" ? "自定义词库" : "内置词库" },
          ]} />
          <Space wrap style={{ marginTop: 12 }}>
            {guard.patterns.map((rule) => <Tag key={rule.id}>{rule.id} · 配置{ON_OFF(rule.enabled)}</Tag>)}
          </Space>
        </>}
      </section>
      <section className="settings-section" aria-label="虚构样例自检">
        <Space wrap>
          <h4>虚构样例自检</h4>
          <Button size="small" disabled={!snapshot || loading} loading={checking} onClick={() => void runCheck()}>运行样例自检</Button>
        </Space>
        <p>使用固定虚构输入调用现有脱敏函数。自检不调用模型或 MCP，不覆盖完整对话、提示注入或有害内容处置。</p>
        {checkError && <Alert type="error" showIcon message={checkError} />}
        {check && <>
          <p>检查时间：{CLOCK(check.checked_at)} · 输出脱敏{ON_OFF(check.active)}</p>
          <Table rowKey="label" size="small" pagination={false} scroll={{ x: 640 }} dataSource={check.results} columns={[
            { title: "样例", dataIndex: "label" },
            { title: "虚构输入", dataIndex: "input" },
            { title: "实际输出", dataIndex: "output" },
            { title: "观察结果", dataIndex: "changed", render: (changed: boolean) => changed ? "内容已改变" : "内容未改变" },
            { title: "命中规则", dataIndex: "hit_ids", render: (ids: string[]) => ids.join("、") || "—" },
          ]} />
        </>}
      </section>
      <section className="settings-section" aria-label="外部服务与端点管控">
        <h4>外部服务与端点管控</h4>
        {snapshot && <p>生产保护配置：{ON_OFF(snapshot.mcp_boundary.production_guards)} · 显式声明的 MCP 主机数：{snapshot.mcp_boundary.declared_host_count}</p>}
        <p>主机数不含内置本机和服务域名许可。网络可达性、证书、端侧管控与实际策略生效情况需要另行验证。</p>
        <Link to="/mcp">查看 MCP 服务与工具权限</Link>
      </section>
      <section className="settings-section" aria-label="技能扫描范围">
        <h4>技能扫描范围</h4>
        <p>技能扫描用于导入和审核检查。扫描记录不能证明运行时提示注入防护或完整内容安全覆盖。</p>
      </section>
    </div>
  );
}

function PolicyAudit() {
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
    void securityEvidenceApi.audit(query, controller.signal).then((result) => {
      if (!controller.signal.aborted) setData(result);
    }).catch((error) => {
      if (!controller.signal.aborted) setError(ERROR_TEXT(error));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [query]);

  const page = Number(query.offset) / PAGE_SIZE + 1;
  const exportPage = () => {
    if (!data?.records.length) return;
    const fields = ["ts", "agent_id", "session_id", "tool_name", "target", "decision", "reason"] as const;
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
    link.download = `policy-audit-page-${page}.csv`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <section className="settings-section" aria-label="策略审计">
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Alert type="info" showIcon message="这里记录工具策略决策，执行结果未记录。审计留存期与防篡改能力需另行验证。" />
        <Space wrap>
          <Input aria-label="智能体 ID" placeholder="智能体 ID" maxLength={200} value={draft.agent_id}
            onChange={(event) => setDraft({ ...draft, agent_id: event.target.value })} />
          <Input aria-label="工具名称" placeholder="工具名称" maxLength={200} value={draft.tool_name}
            onChange={(event) => setDraft({ ...draft, tool_name: event.target.value })} />
          <Select aria-label="策略决策" value={draft.decision} style={{ width: 120 }}
            options={[{ value: "", label: "全部决策" }, ...Object.entries(DECISIONS).map(([value, label]) => ({ value, label }))]}
            onChange={(decision) => setDraft({ ...draft, decision })} />
          <DatePicker.RangePicker showTime placeholder={["开始时间", "结束时间"]}
            onChange={(values) => setTimes(values?.[0] && values[1] ? { since: values[0].valueOf(), until: values[1].valueOf() } : {})} />
          <Button loading={loading} onClick={() => setQuery({
            ...Object.fromEntries(Object.entries(draft).map(([key, value]) => [key, value.trim()]).filter(([, value]) => value)),
            ...times, offset: 0, limit: PAGE_SIZE,
          })}>查询</Button>
          <Button disabled={loading || !data?.records.length} onClick={exportPage}>导出当前显示页</Button>
        </Space>
        {error && <Alert type="error" showIcon message={error} />}
        {data && <span>数据源：{data.source} · 读取时间：{CLOCK(data.queried_at)}</span>}
        {data?.storage_status === "not_created" && <Alert type="info" message="尚无审计数据库。" />}
        {data?.storage_status === "unsupported_schema" && <Alert type="warning" message="现有审计库结构不支持只读展示，数据未迁移。" />}
        <Table<AuditRecord> rowKey="rowid" size="small" loading={loading} dataSource={data?.records ?? []}
          scroll={{ x: 950 }} locale={{ emptyText: error ? "数据未读取" : "没有匹配的可读策略记录" }}
          pagination={{ current: page, pageSize: PAGE_SIZE, total: Math.min(data?.total ?? 0, 100000 + PAGE_SIZE), showSizeChanger: false,
            onChange: (next) => setQuery((current) => ({ ...current, offset: (next - 1) * PAGE_SIZE })) }}
          columns={[
            { title: "时间", dataIndex: "ts", render: CLOCK },
            { title: "智能体 ID", dataIndex: "agent_id" },
            { title: "会话 ID", dataIndex: "session_id" },
            { title: "工具", dataIndex: "tool_name" },
            { title: "目标（脱敏）", dataIndex: "target" },
            { title: "策略决策", dataIndex: "decision", render: (value: keyof typeof DECISIONS) => DECISIONS[value] || value },
            { title: "原因（脱敏）", dataIndex: "reason" },
          ]} />
      </Space>
    </section>
  );
}

export function PortalSecurityEvidence() {
  return <Tabs destroyOnHidden items={[
    { key: "protection", label: "防护概览", children: <ProtectionOverview /> },
    { key: "audit", label: "策略审计", children: <PolicyAudit /> },
  ]} />;
}
