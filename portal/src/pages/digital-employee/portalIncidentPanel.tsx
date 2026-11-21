import { useEffect, useState, type CSSProperties } from "react";
import { Alert, Checkbox, Modal, Pagination, Select, Table, theme } from "antd";
import {
  portalIncidentsApi, riskLabels,
  type IncidentBatch, type IncidentDetail, type IncidentRisk, type IncidentTask, type IncidentView,
} from "../../api/portalIncidents";
import "./portalIncidentPanel.css";

const TIME = (seconds: number | null | undefined) => seconds == null
  ? "—" : new Date(seconds * 1000).toLocaleString("zh-CN", { hour12: false });
const SCOPE = "仅控制本实例内受管的 Portal 流式对话（含继续回复和 CMDB 重试）。不控制独立后台任务、其他渠道或已发出的远程操作。";
const RISK_LABEL = (reason: IncidentBatch["reason"]) => reason === "maintenance" ? "运维关停" : riskLabels[reason] ?? "未记录分类";
const STATUS_LABELS: Record<string, string> = {
  accepted: "待确认停止", cancelled: "已确认取消", completed: "已结束 · 未确认中止",
  timeout: "超时结束", failed: "异常结束", unknown: "无法确认",
};

function feedback(error: unknown, fallback: string) {
  return error instanceof Error && error.name === "Error" ? error.message : fallback;
}

function Badge({ text, tone = "neutral" }: { text: string; tone?: "success" | "warning" | "danger" | "neutral" }) {
  return <span className={`security-evidence-badge ${tone}`}>{text}</span>;
}

function BatchStatus({ batch }: { batch: IncidentBatch }) {
  if (batch.total === null) return <Badge text="未取得处置结果" tone="warning" />;
  const confirmed = batch.counts.cancelled ?? 0;
  return <div className="incident-batch-results">
    {batch.total === 0 ? <Badge text="无运行中对话" /> : <Badge text={`确认取消 ${confirmed} / ${batch.total}`} tone={confirmed === batch.total ? "success" : "neutral"} />}
    {Object.entries(batch.counts).filter(([status]) => status !== "cancelled").map(([status, count]) =>
      <Badge key={status} text={`${STATUS_LABELS[status] ?? "未确认"} ${count}`} tone={status === "accepted" || status === "unknown" ? "warning" : "neutral"} />)}
  </div>;
}

function BatchDetails({ batch, onClose }: { batch: IncidentBatch; onClose: () => void }) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<IncidentDetail>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void portalIncidentsApi.detail(batch.id, page, controller.signal).then((result) => {
      if (!controller.signal.aborted) setData(result);
    }).catch((err) => {
      if (!controller.signal.aborted) {
        setData(undefined);
        setError(feedback(err, "无法读取批次明细，请关闭后重试。"));
      }
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [batch.id, page]);
  const current = data?.batch ?? batch;
  const { token } = theme.useToken();
  const badgeTheme = {
    "--bg-gray": token.colorFillSecondary,
    "--text-secondary": token.colorTextSecondary,
    "--evidence-positive": token.colorSuccessText,
    "--evidence-caution": token.colorWarningText,
  } as CSSProperties;
  return <Modal open title="处置批次明细" footer={null} width={1000} onCancel={onClose}>
    <div className="incident-detail" style={badgeTheme}>
      <div className="incident-detail-meta">
        <div><b>批次编号</b><code>{current.id}</code></div>
        <div><b>中止触发</b>{RISK_LABEL(current.reason)} · {TIME(current.at)} · {current.actor ?? "未记录"}</div>
        <div><b>恢复记录</b>{current.resume ? `${TIME(current.resume.at)} · ${current.resume.actor ?? "未记录"}` : "未恢复或未记录"}</div>
        {current.elapsed_ms !== null && <div><b>首次结果统计用时</b>{current.elapsed_ms} ms</div>}
      </div>
      <BatchStatus batch={current} />
      <p>台账仅保留处置元数据。检查点保存在原会话；此处的「已保存」仅反映当时的写入结果。</p>
      {error && <Alert showIcon type="error" title={error} />}
      <Table<IncidentTask> size="small" rowKey={(row) => `${row.agent_id ?? ""}:${row.chat_id}:${row.turn_id ?? ""}`}
        loading={loading} dataSource={loading ? [] : data?.tasks ?? []} scroll={{ x: 880 }}
        locale={{ emptyText: error ? "明细未读取" : current.total === null ? "批次未取得任务结果" : "没有纳入本批次的任务" }}
        pagination={data?.batch.total && data.batch.total > data.page_size ? {
          current: page, pageSize: data.page_size, total: data.batch.total, showSizeChanger: false, onChange: setPage,
        } : false}
        columns={[
          { title: "智能体 / 会话 / 轮次 ID", key: "task", width: 305, render: (_, task) => <div className="incident-detail-ids">
            <code>{task.agent_id || "—"}</code><code>{task.chat_id}</code>{task.turn_id && <code>{task.turn_id}</code>}
          </div> },
          { title: "开始时间", dataIndex: "started_at", render: TIME, width: 156 },
          { title: "本地结束时间", dataIndex: "finished_at", render: TIME, width: 156 },
          { title: "处置结果", dataIndex: "status", render: (status: string) => STATUS_LABELS[status] ?? "未确认" },
          { title: "会话检查点", dataIndex: "checkpoint_saved", render: (saved: boolean | null) => saved === true
            ? <Badge text="已保存" tone="success" /> : saved === false ? <Badge text="未确认保存" tone="warning" /> : "—" },
        ]} />
    </div>
  </Modal>;
}

export function PortalIncidentPanel() {
  const [view, setView] = useState<IncidentView>();
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [dialog, setDialog] = useState<"stop" | "resume">();
  const [risk, setRisk] = useState<IncidentRisk>();
  const [reviewed, setReviewed] = useState(false);
  const [selected, setSelected] = useState<IncidentBatch>();
  const [reviewBatch, setReviewBatch] = useState<IncidentBatch>();

  const refresh = () => setRevision((value) => value + 1);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError("");
    void portalIncidentsApi.list(page, controller.signal).then((result) => {
      if (!controller.signal.aborted) setView(result);
    }).catch((err) => {
      if (!controller.signal.aborted) {
        setView(undefined);
        setLoadError(feedback(err, "无法读取异常中止状态，请刷新重试。"));
      }
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [page, revision]);

  const data = view?.enabled ? view : undefined;
  const latest = data?.latest;
  const pending = latest?.counts.accepted ?? 0;
  const busy = loading || saving;
  const canResume = Boolean(data?.paused && latest && !pending && data.active_count === 0);
  const unconfirmed = latest && (latest.total === null || Boolean(latest.counts.unknown));
  const blocked = busy || !data || Boolean(loadError || actionError);

  function openDialog(action: "stop" | "resume") {
    setRisk(undefined);
    setReviewed(false);
    setReviewBatch(action === "resume" ? latest ?? undefined : undefined);
    setDialog(action);
  }

  async function change() {
    if (saving) return;
    const action = dialog === "stop" && risk ? () => portalIncidentsApi.stop(risk)
      : dialog === "resume" && reviewed && reviewBatch ? () => portalIncidentsApi.resume(reviewBatch.id) : null;
    if (!action) return;
    setSaving(true);
    setActionError("");
    try {
      setView(await action());
      setPage(1);
    } catch (err) {
      setActionError(feedback(err, "未能确认操作结果。请先刷新状态，不要重复提交。"));
    } finally {
      setSaving(false);
      setDialog(undefined);
    }
  }

  return <div className="security-evidence-stack">
    <section className="security-evidence-card" aria-labelledby="incident-title" aria-busy={busy}>
      <div className="security-evidence-heading">
        <span className="settings-tab-icon" aria-hidden="true">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M12 22s7-3.5 7-9V5l-7-3-7 3v8c0 5.5 7 9 7 9z M12 7v5m0 3v2" />
          </svg>
        </span>
        <div className="security-evidence-heading-copy">
          <h4 id="incident-title">异常中止控制</h4>
          <p>发现安全风险时，由管理员暂停新请求并取消运行中的本地对话。</p>
        </div>
        <button type="button" className="portal-model-btn secondary" disabled={busy} onClick={() => { setActionError(""); refresh(); }}>
          {loading ? "正在读取…" : "刷新状态"}
        </button>
      </div>
      <dl className="security-evidence-metrics">
        <div><dt>入口状态</dt><dd>{data ? (data.paused
          ? <Badge text="已暂停接收" tone="danger" /> : <Badge text="正常接收" tone="success" />)
          : <Badge text={view?.enabled === false ? "未启用" : "未确认"} />}</dd></div>
        <div><dt>本实例运行中</dt><dd>{data?.active_count ?? "—"}</dd></div>
        <div><dt>最近批次已确认取消</dt><dd>{latest && latest.total !== null ? `${latest.counts.cancelled ?? 0} / ${latest.total}` : "—"}</dd></div>
        <div><dt>最近一次中止</dt><dd>{TIME(latest?.at)}</dd></div>
      </dl>
      {loadError && <Alert type="error" showIcon title={loadError} />}
      {actionError && <Alert type="warning" showIcon title={actionError} />}
      {view?.enabled === false && <Alert type="warning" showIcon title="当前部署未启用 Portal 会话隔离，异常中止不可操作。" />}
      {data?.paused && pending > 0 && <Alert type="warning" showIcon title={`有 ${pending} 个任务待确认停止，请刷新核对后再恢复。`} />}
      {data?.paused && unconfirmed && <Alert type="warning" showIcon title="有未取得的处置结果，请先核对现场；无法确认不等于已经停止。" />}
      <div className="incident-control-bar">
        <div className="security-evidence-actions">
          <button type="button" className="portal-model-btn incident-stop" disabled={blocked || Boolean(data?.paused)} onClick={() => openDialog("stop")}>启动异常中止</button>
          <button type="button" className="portal-model-btn secondary" disabled={blocked || !canResume} onClick={() => openDialog("resume")}>复核并恢复</button>
        </div>
        <span className="security-evidence-note" role="status">{data ? `状态读取时间：${TIME(data.queried_at)}` : ""}</span>
      </div>
      <p className="security-evidence-note">{SCOPE} 已发出的数据不可撤回；中止不等于外部断网或业务回滚。本页由管理员触发，不自动识别风险。</p>
    </section>
    <section className="security-evidence-card" aria-labelledby="incident-history-title" aria-busy={loading}>
      <div className="security-evidence-heading">
        <div className="security-evidence-heading-copy">
          <h4 id="incident-history-title">处置台账</h4>
          <p>{data ? `本地保留最近 ${data.retention_limit} 个中止批次。` : ""}记录触发分类、操作者、任务处置和复核恢复，不收集正文、工具参数或凭据。</p>
        </div>
        {data && <Badge text={`${data.total} 个批次`} />}
      </div>
      <div className="security-evidence-table-group">
        <div className="security-evidence-table-scroll" role="region" aria-labelledby="incident-history-title" tabIndex={0}>
          <table className="security-evidence-monitor-table incident-history-table" aria-labelledby="incident-history-title">
            <thead><tr>{["中止时间 / 批次", "触发分类", "操作者", "本地处置结果", "恢复时间 / 操作者", "明细"].map((label) => <th key={label} scope="col">{label}</th>)}</tr></thead>
            <tbody>{data?.records.length ? data.records.map((batch) => <tr key={batch.id}>
              <th scope="row">{TIME(batch.at)}<code className="incident-batch-id" title={batch.id}>{batch.id.slice(0, 8)}</code></th>
              <td>{RISK_LABEL(batch.reason)}</td>
              <td className="incident-actor">{batch.actor ?? "未记录"}</td>
              <td><BatchStatus batch={batch} /></td>
              <td>{batch.resume ? <>{TIME(batch.resume.at)}<span className="incident-subline incident-actor">{batch.resume.actor ?? "未记录"}</span></>
                : data.paused && latest?.id === batch.id ? "待复核恢复" : "未记录"}</td>
              <td><button type="button" className="settings-link-btn" aria-label={`查看批次 ${batch.id.slice(0, 8)} 明细`} onClick={() => setSelected(batch)}>查看</button></td>
            </tr>) : <tr><td colSpan={6} className="security-evidence-empty">{loading ? "正在读取处置记录…" : data ? "尚无中止处置记录" : "处置记录未读取"}</td></tr>}</tbody>
          </table>
        </div>
      </div>
      {data && data.total > data.page_size && <Pagination current={page} pageSize={data.page_size} total={data.total}
        showSizeChanger={false} disabled={busy} onChange={setPage} />}
    </section>
    {selected && <BatchDetails batch={selected} onClose={() => setSelected(undefined)} />}
    {dialog && <Modal open title={dialog === "stop" ? "确认启动异常中止" : "复核并恢复入口"}
      onCancel={() => { if (!saving) setDialog(undefined); }} onOk={() => void change()}
      cancelText="取消" okText={dialog === "stop" ? "确认中止" : "确认恢复"} confirmLoading={saving}
      okButtonProps={{ danger: dialog === "stop", disabled: dialog === "stop" ? !risk : !reviewed }}>
      {dialog === "stop" ? <div className="incident-detail">
        <p>新请求将暂停受理；服务端会对运行中的本地对话发出取消请求，丢弃仍在队列的流式输出，并保存处置记录。已发出的远程操作仍需另行核查。</p>
        <label htmlFor="incident-risk">触发风险（由管理员登记）</label>
        <Select id="incident-risk" aria-label="触发风险" placeholder="请选择风险分类" value={risk} onChange={setRisk} disabled={saving}
          options={Object.entries(riskLabels).map(([value, label]) => ({ value, label }))} />
      </div> : <div className="incident-detail">
        <p>仅恢复接收新请求，不自动重启已中止的任务，也不撤销已发生的业务操作。</p>
        {reviewBatch && <p>复核批次：<code>{reviewBatch.id}</code></p>}
        <Checkbox checked={reviewed} disabled={saving} onChange={(event) => setReviewed(event.target.checked)}>我已核对风险、任务状态及相关处置记录，确认恢复。</Checkbox>
      </div>}
    </Modal>}
  </div>;
}
