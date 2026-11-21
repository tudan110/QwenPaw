import { useEffect, useState } from "react";
import { Alert, Button, DatePicker, Input, Select, Space, Table, Tag } from "antd";
import { AuditOutlined, DownloadOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import {
  criticalAuditApi, type AuditKind, type AuditStorage, type AuditVerification,
  type CriticalAuditFilters, type CriticalAuditPage, type CriticalAuditRecord,
} from "../../api/criticalAudit";
import "./criticalAuditPanel.css";

const KINDS: Record<AuditKind, string> = {
  governance_activity: "治理操作", tool_execution: "工具执行", policy_decision: "策略决策",
};
const DECISIONS: Record<string, string> = { allow: "允许", deny: "拒绝", ask: "需审批", sandbox_fallback: "沙箱执行" };
const RESULTS: Record<string, string> = {
  started: "已开始 · 终态见后续记录", success: "执行成功", error: "执行失败", denied: "已拒绝",
  cancelled: "已取消", returned: "已返回 · 业务结果未确认", unconfirmed: "结果未确认",
  http_completed: "请求完成 · 不代表业务成功", http_error: "请求失败", http_other: "其他响应",
};
const STORAGE: Record<AuditStorage["state"], string> = {
  protected: "只追加保护已启用", unsealed: "历史库尚未建立完整性基线", not_created: "尚未创建审计库",
  unsupported_schema: "历史库结构暂不支持", protection_missing: "保护结构缺失或异常", tail_mismatch: "审计库与校验链末端不一致",
};
const clock = new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "medium", hour12: false, timeZone: "Asia/Shanghai" });
const emptyDraft = { kind: "", subject: "", operation: "", result: "" };
const errorText = (error: unknown) => error instanceof Error && error.name !== "TimeoutError"
  ? error.message : "请求超时，请稍后重试。";

function AuditProtection({ data }: { data: CriticalAuditPage }) {
  const [anchor, setAnchor] = useState("");
  const [verification, setVerification] = useState<AuditVerification>();
  const [error, setError] = useState("");
  const [controller, setController] = useState<AbortController>();
  useEffect(() => () => controller?.abort(), [controller]);
  const verify = async () => {
    const request = new AbortController();
    setController(request);
    setVerification(undefined);
    setError("");
    try {
      const outcome = await criticalAuditApi.verify(anchor.trim(), request.signal);
      if (!request.signal.aborted) setVerification(outcome);
    } catch (error) {
      if (!request.signal.aborted) setError(errorText(error));
    } finally {
      if (!request.signal.aborted) setController(undefined);
    }
  };
  const { storage, retention } = data;
  const verified = verification?.state === "verified";
  const bad = ["protection_missing", "tail_mismatch"].includes(storage.state);
  return <section className="security-evidence-card critical-audit-protection" aria-labelledby="critical-audit-protection-title">
    <h4 id="critical-audit-protection-title"><SafetyCertificateOutlined aria-hidden /> 防护与留存</h4>
    <dl className="security-evidence-metrics">
      <div><dt>本地写入保护</dt><dd><Tag color={storage.state === "protected" ? "green" : bad ? "red" : "orange"}>{STORAGE[storage.state]}</Tag></dd></div>
      <div><dt>留存基线</dt><dd>不少于 {retention.minimum_months} 个月</dd></div>
      <div><dt>重要数据／个人信息归档基线</dt><dd>{retention.extended_months} 个月</dd></div>
      <div><dt>独立归档</dt><dd><Tag color="orange">未验证</Tag></dd></div>
    </dl>
    <p className="security-evidence-note">本地不自动清理，页面不提供修改、删除或缩短留存的入口。延长基线是部署配置，不是统一法定期限；适用要求更长时，应提高归档期限。独立防删除仍需启用不可变归档并做恢复演练。</p>
    {!retention.valid_configuration && <Alert type="warning" showIcon title="延长留存配置无效，当前显示 36 个月默认基线，请联系运维修正配置。" />}
    {storage.sealed_at && <p className="security-evidence-note">
      基线建立于 {clock.format(new Date(storage.sealed_at))}。{Boolean(storage.legacy_through) && "历史记录从基线建立时起可校验，基线之前的真实性无法追溯。"}
    </p>}
    <form className="security-evidence-filters critical-audit-verify" aria-label="完整性校验" onSubmit={(event) => { event.preventDefault(); void verify(); }}>
      <Input aria-label="独立留存的锚点（可选）" placeholder="独立留存的锚点（可选）" value={anchor} maxLength={120}
        disabled={!!controller} onChange={(event) => { setAnchor(event.target.value); setVerification(undefined); setError(""); }} />
      <Button htmlType="submit" icon={<SafetyCertificateOutlined />} loading={!!controller} disabled={storage.state === "not_created"}>校验完整性</Button>
    </form>
    {error && <Alert type="error" showIcon title={error} />}
    {verification && <Alert showIcon type={verified ? "success" : "error"} title={verified
      ? `本地完整性校验通过，共核对 ${verification.checked_events} 条${verification.external_match ? "；独立锚点匹配" : "；未比对独立锚点"}`
      : verification.state === "mismatch" ? `校验链不一致${verification.first_bad_id ? `（记录 #${verification.first_bad_id}）` : ""}`
        : verification.state === "checkpoint_mismatch" ? "独立锚点不匹配：请排查数据库重建、回滚或截断"
          : STORAGE[verification.state as AuditStorage["state"]]}
      description={verified && verification.checkpoint ? <div className="critical-audit-checkpoint">
        <p>{clock.format(new Date(verification.checked_at))} · 请将锚点保存到独立的不可变归档中。锚点不是日志备份。</p>
        <Space.Compact block><Input aria-label="本次校验锚点" readOnly value={verification.checkpoint} />
          <Button href={`data:text/plain;charset=utf-8,${encodeURIComponent(verification.checkpoint)}`} download="critical-audit-checkpoint.txt">下载锚点</Button>
        </Space.Compact>
      </div> : undefined} />}
  </section>;
}

export function CriticalAuditPanel() {
  const [draft, setDraft] = useState(emptyDraft);
  const [dates, setDates] = useState<[number, number]>();
  const [filters, setFilters] = useState<CriticalAuditFilters>({});
  const [cursors, setCursors] = useState<(number | undefined)[]>([undefined]);
  const [snapshot, setSnapshot] = useState<number>();
  const [data, setData] = useState<CriticalAuditPage>();
  const [policyData, setPolicyData] = useState<CriticalAuditPage>();
  const [error, setError] = useState("");
  const [exportError, setExportError] = useState("");
  const [loading, setLoading] = useState(true);
  const [exportRequest, setExportRequest] = useState<AbortController>();
  const cursor = cursors[cursors.length - 1];
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setExportError("");
    setData(undefined);
    const query = { ...filters, ...(cursor !== undefined ? { before_id: cursor } : {}),
      ...(snapshot !== undefined ? { through_id: snapshot } : {}) };
    void criticalAuditApi.list(query, controller.signal).then((result) => {
      if (!controller.signal.aborted) { setData(result); setPolicyData(result); }
    }).catch((error) => {
      if (!controller.signal.aborted) { setError(errorText(error)); setPolicyData(undefined); }
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [filters, cursor, snapshot]);
  useEffect(() => () => exportRequest?.abort(), [exportRequest]);

  const query = (values: typeof draft, range?: [number, number]) => {
    setCursors([undefined]);
    setSnapshot(undefined);
    setFilters({ ...Object.fromEntries(Object.entries(values).map(([key, value]) => [key, value.trim()]).filter(([, value]) => value)),
      ...(range ? { since: range[0], until: range[1] } : {}) });
  };
  const exportPage = async () => {
    if (!data?.records.length) return;
    const controller = new AbortController();
    setExportRequest(controller);
    setExportError("");
    try {
      const blob = await criticalAuditApi.export({ ...filters, through_id: data.through_id,
        ...(cursor !== undefined ? { before_id: cursor } : {}) }, controller.signal);
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "critical-audit.csv";
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      if (!controller.signal.aborted) setExportError(errorText(error));
    } finally {
      if (!controller.signal.aborted) setExportRequest(undefined);
    }
  };
  const next = data?.next_before_id;
  return <div className="security-evidence-stack critical-audit">
    {policyData && <AuditProtection data={policyData} />}
    <section className="security-evidence-card" aria-labelledby="critical-audit-title" aria-busy={loading}>
      <header className="security-evidence-heading">
        <div className="security-evidence-heading-copy">
          <h4 id="critical-audit-title"><AuditOutlined aria-hidden /> 关键活动记录</h4>
          <p>按写入顺序展示治理操作、工具执行和策略决策。表格显示北京时间，筛选时间按浏览器时区输入，CSV 提供 UTC 时间。</p>
        </div>
        <Button icon={<DownloadOutlined />} loading={!!exportRequest} disabled={loading || !data?.records.length || data.storage.state !== "protected"}
          onClick={() => void exportPage()}>导出当前页 CSV</Button>
      </header>
      <form className="security-evidence-filters critical-audit-filters" aria-label="关键活动筛选" onSubmit={(event) => { event.preventDefault(); query(draft, dates); }}>
        <Select aria-label="操作类型" value={draft.kind} onChange={(kind) => setDraft({ ...draft, kind })}
          options={[{ value: "", label: "全部类型" }, ...Object.entries(KINDS).map(([value, label]) => ({ value, label }))]} />
        <Input aria-label="操作主体 ID" placeholder="主体 ID（精确）" maxLength={200} value={draft.subject}
          onChange={(event) => setDraft({ ...draft, subject: event.target.value })} />
        <Input aria-label="操作名称" placeholder="操作名称（精确）" maxLength={200} value={draft.operation}
          onChange={(event) => setDraft({ ...draft, operation: event.target.value })} />
        <Select aria-label="执行结果或策略决策" value={draft.result} onChange={(result) => setDraft({ ...draft, result })}
          options={[{ value: "", label: "全部结果" }, ...Object.entries({ ...DECISIONS, ...RESULTS }).map(([value, label]) => ({ value, label }))]} />
        <DatePicker.RangePicker showTime placeholder={["开始时间", "结束时间"]}
          onChange={(values) => setDates(values?.[0] && values[1] ? [values[0].valueOf(), values[1].valueOf()] : undefined)} />
        <Button type="primary" htmlType="submit" loading={loading} disabled={!!exportRequest}>查询／刷新</Button>
      </form>
      {error && <Alert type="error" showIcon title={error} />}
      {exportError && <Alert type="error" showIcon title={exportError} />}
      {data && data.storage.state !== "protected" && <Alert type="warning" showIcon title={STORAGE[data.storage.state]} />}
      <Table<CriticalAuditRecord> size="small" rowKey="id" loading={loading} dataSource={data?.records ?? []} pagination={false}
        scroll={{ x: 1060 }} locale={{ emptyText: error ? "数据未读取" : "没有匹配的审计记录" }}
        columns={[
          { title: "时间", dataIndex: "ts", width: 158, render: (ts: number | null) => ts != null && Number.isFinite(ts) ? clock.format(ts) : "未记录" },
          { title: "操作主体", width: 150, render: (_, row) => <>
            <span>{row.subject_kind === "anonymous" ? "未验证身份" : row.subject}</span>
            {row.subject_kind === "agent" && <Tag>智能体</Tag>}
          </> },
          { title: "操作类型 / 名称", width: 225, render: (_, row) => <><Tag>{KINDS[row.kind]}</Tag><code>{row.operation}</code></> },
          { title: "操作对象（最小披露）", dataIndex: "target", width: 200 },
          { title: "执行结果", width: 230, render: (_, row) => row.kind === "policy_decision"
            ? <><Tag>非执行结果</Tag>{DECISIONS[row.decision ?? ""] ?? row.decision ?? "未记录"}</>
            : <>{RESULTS[row.result] ?? "未确认"}{row.http_status ? ` · HTTP ${row.http_status}` : ""}</> },
          { title: "审计编号", width: 160, render: (_, row) => <><code>#{row.id}</code>{row.id <= (data?.storage.legacy_through ?? 0) && <Tag>历史基线</Tag>}{row.call_id && <span className="critical-audit-call-id" title={row.call_id}>调用：{row.call_id}</span>}</> },
        ]} />
      <div className="critical-audit-pager">
        <span>第 {cursors.length} 页{data ? ` · ${data.records.length} 条` : ""}</span>
        <Space>
          <Button disabled={loading || !!exportRequest || cursors.length < 2} onClick={() => setCursors((pages) => pages.slice(0, -1))}>上一页</Button>
          <Button disabled={loading || !!exportRequest || next == null} onClick={() => {
            if (data && next != null) { setSnapshot(data.through_id); setCursors((pages) => [...pages, next]); }
          }}>下一页</Button>
        </Space>
      </div>
    </section>
  </div>;
}
