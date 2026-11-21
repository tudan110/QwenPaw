import { useEffect, useState } from "react";
import { Alert, Button, Card, Input, Modal, Select, Space, Table, Tag, Typography } from "antd";
import { Link } from "react-router-dom";
import {
  callAdmissionApi, type AdmissionChange, type AdmissionKind, type AdmissionPolicies,
  type AdmissionPolicyCheck, type AdmissionPolicyRow, type AdmissionRisk,
} from "../../api/callAdmission";

const kinds: Record<AdmissionKind, string> = {
  tool: "Agent 工具", script: "受管脚本", api: "业务 API", mcp_service: "MCP 服务", mcp_tool: "MCP 工具",
};
const risks: Record<AdmissionRisk, { label: string; color: string }> = {
  low: { label: "低", color: "green" }, medium: { label: "中", color: "blue" },
  high: { label: "高", color: "orange" }, critical: { label: "极高", color: "red" },
};
const kindOptions = (Object.keys(kinds) as AdmissionKind[]).map((value) => ({ value, label: kinds[value] }));
const riskOptions = (Object.keys(risks) as AdmissionRisk[]).map((value) => ({ value, label: risks[value].label }));
const decisionOptions = [
  { value: "inherit", label: "沿用既有策略" }, { value: "deny", label: "禁止调用" },
];
const formatTime = (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false });
const errorText = (error: unknown) => error instanceof Error && error.name !== "TimeoutError"
  ? error.message : "请求未完成，请刷新后确认。";

export function CallAdmissionControls({ revision, initialCategory = "all" }: {
  revision: number; initialCategory?: AdmissionKind | "all";
}) {
  const [snapshot, setSnapshot] = useState<AdmissionPolicies>();
  const [loadError, setLoadError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [category, setCategory] = useState<AdmissionKind | "all">(initialCategory);
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState<AdmissionChange>();
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [saved, setSaved] = useState("");
  const [checking, setChecking] = useState<string>();
  const [checkError, setCheckError] = useState("");
  const [check, setCheck] = useState<{ row: AdmissionPolicyRow; result: AdmissionPolicyCheck }>();

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError("");
    setCheck(undefined);
    setCheckError("");
    void callAdmissionApi.list(controller.signal).then((data) => {
      if (!controller.signal.aborted) setSnapshot(data);
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) {
        setSnapshot(undefined);
        setLoadError(errorText(error));
      }
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [revision, reload]);

  const open = (row?: AdmissionPolicyRow) => {
    setFormError("");
    setAdding(!row);
    setDraft(row ? {
      kind: row.kind, name: row.name, service: row.service, revision: row.revision,
      risk: row.risk, decision: row.decision, reason: "",
    } : { kind: "mcp_tool", name: "", service: "", revision: 0, risk: "high", decision: "inherit", reason: "" });
  };
  const update = (patch: Partial<AdmissionChange>) => setDraft((value) => value && { ...value, ...patch });
  const save = async () => {
    if (!draft || saving) return;
    const name = draft.name.trim();
    const service = draft.service.trim();
    const reason = draft.reason.trim();
    if (!name || !reason || (draft.kind === "mcp_tool" && !service)) {
      setFormError("请填写精确标识和本次评估或变更理由。");
      return;
    }
    if (adding && snapshot?.items.some((row) => row.kind === draft.kind && row.name === name && row.service === service)) {
      setFormError("该对象已在清单中，请从该行进入编辑。");
      return;
    }
    setSaving(true);
    setFormError("");
    setSaved("");
    try {
      const row = await callAdmissionApi.save({ ...draft, name, service, reason });
      setSaved(`已保存 ${row.service ? `${row.service} / ` : ""}${row.name} · 版本 ${row.revision}。`);
      setDraft(undefined);
      setCategory(row.kind);
      setQuery(row.name);
      setReload((value) => value + 1);
    } catch (error) {
      setFormError(errorText(error));
    } finally {
      setSaving(false);
    }
  };
  const runCheck = async (row: AdmissionPolicyRow) => {
    setChecking(row.id);
    setCheck(undefined);
    setCheckError("");
    try { setCheck({ row, result: await callAdmissionApi.check(row) }); }
    catch (error) { setCheckError(errorText(error)); }
    finally { setChecking(undefined); }
  };

  const rows = snapshot?.items.filter((row) => (category === "all" || category === row.kind)
    && `${row.service} ${row.name} ${kinds[row.kind]}`.toLowerCase().includes(query.trim().toLowerCase())) ?? [];
  const checkTarget = check ? [check.row.service, check.row.name].filter(Boolean).join(" / ") : "";
  const checkDescription = check ? `${formatTime(check.result.checked_at)} · 只校验策略，没有执行工具、发起连接或访问业务数据。` : "";
  return <Card size="small" title="逐项准入控制" extra={<Button type="primary" size="small" disabled={!snapshot || loading || !!checking} onClick={() => open()}>登记调用对象</Button>}>
    <Typography.Paragraph type="secondary">
      禁止调用会在接入的后端入口拦截后续请求；同一后端存储范围内无需重启，不会中止已经发出的调用。
      「沿用既有策略」不是授权，仍受白名单、工作区、用户权限和审批约束。风险等级用于评估，不自动改变准入或审批。
    </Typography.Paragraph>
    <Typography.Paragraph type="secondary">
      系统清单提供基线，不等同于现场已安装或已授权。未列出的工具可按实际标识登记；MCP 服务标识和原始工具名可在 <Link to="/mcp">MCP 管理</Link> 核对。
      端点白名单及未接入的业务 API 不由本表修改。
    </Typography.Paragraph>
    <Space wrap style={{ marginBottom: 12 }}>
      <Select aria-label="按调用类别筛选" value={category} onChange={setCategory} options={[{ value: "all", label: "全部类别" }, ...kindOptions]} style={{ minWidth: 142 }} />
      <Input aria-label="搜索调用对象" placeholder="搜索工具名或服务标识" allowClear value={query} onChange={(event) => setQuery(event.target.value)} />
      <Button size="small" loading={loading} disabled={!!checking} onClick={() => { setSaved(""); setReload((value) => value + 1); }}>刷新列表</Button>
    </Space>
    {loadError && <Alert type="error" showIcon title={loadError} style={{ marginBottom: 12 }} />}
    {saved && <Alert type="success" showIcon title={saved} style={{ marginBottom: 12 }} />}
    {snapshot && !snapshot.production_guards && <Alert type="warning" showIcon title="生产守卫关闭：脚本逐项限制不生效；Shell 整体禁用及其他接入范围的禁用仍有效。" style={{ marginBottom: 12 }} />}
    {checkError && <Alert type="error" showIcon title={checkError} style={{ marginBottom: 12 }} />}
    {check && (check.result.decision === "deny" ? <Alert showIcon type="success" style={{ marginBottom: 12 }}
      title={`${checkTarget}：策略判定：拒绝（命中 ${check.result.blocked_by}）`} description={checkDescription} /> :
      <Typography.Paragraph type="secondary" role="status">
        <strong>{checkTarget}：{check.result.decision === "inactive" ? "逐项脚本策略当前未执行" : "本层未拦截，仍需通过既有策略"}</strong>
        <br />{checkDescription}
      </Typography.Paragraph>)}
    <Table<AdmissionPolicyRow> className="gov-table gov-inner-table" size="small" rowKey="id" loading={loading} dataSource={rows}
      pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (total) => `${total} 项` }} scroll={{ x: 1000 }} columns={[
        { title: "调用对象", width: 270, render: (_, row) => <>
          <Tag>{kinds[row.kind]}</Tag>{row.service && <Typography.Text type="secondary">{row.service}</Typography.Text>}
          <br /><Typography.Text code style={{ overflowWrap: "anywhere" }}>{row.name}</Typography.Text>
        </> },
        { title: "启用条件与权限边界", dataIndex: "boundary" },
        { title: "风险等级", width: 145, render: (_, row) => <>
          <Tag color={risks[row.risk].color}>{risks[row.risk].label}</Tag>{row.risk_source === "manual" ? "人工评估" : "系统基线"}
          {row.reason && <><br /><Typography.Text type="secondary" style={{ overflowWrap: "anywhere" }}>{row.reason}</Typography.Text></>}
        </> },
        { title: "本项准入配置", width: 144, render: (_, row) => <>
          <Tag color={row.decision === "deny" ? "red" : "default"}>{row.decision === "deny" ? "禁止调用" : "沿用既有策略"}</Tag>
          {row.kind === "script" && !snapshot?.production_guards && <><br /><Tag color="orange">逐项限制未执行</Tag></>}
          {row.updated_at && <><br /><Typography.Text type="secondary">版本 {row.revision}</Typography.Text></>}
        </> },
        { title: "操作", width: 160, render: (_, row) => <Space size={4}>
          <Button type="link" size="small" disabled={loading || !!checking} onClick={() => open(row)}>配置</Button>
          <Button type="link" size="small" disabled={loading || !!checking} loading={checking === row.id} onClick={() => void runCheck(row)}>验证准入</Button>
        </Space> },
      ]} />
    <Modal title={adding ? "登记调用对象" : `配置 ${draft?.service ? `${draft.service} / ` : ""}${draft?.name ?? ""}`}
      open={!!draft} onCancel={() => !saving && setDraft(undefined)} confirmLoading={saving} onOk={() => void save()}
      okText="保存策略" cancelText="取消" destroyOnHidden keyboard={!saving} mask={{ closable: !saving }}>
      {draft && <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        {formError && <Alert type="error" showIcon title={formError} />}
        {adding && <>
          <div><Typography.Text>调用类别</Typography.Text><br />
            <Select aria-label="调用类别" value={draft.kind} options={kindOptions.filter(({ value }) => value !== "api" && value !== "script")}
              onChange={(kind) => update({ kind, name: "", service: "" })} style={{ width: "100%" }} disabled={saving} /></div>
          {draft.kind === "mcp_tool" && <label>MCP 服务标识<Input value={draft.service} maxLength={150} disabled={saving} onChange={(event) => update({ service: event.target.value })} /></label>}
          <label>{draft.kind === "mcp_service" ? "MCP 服务标识" : "工具原始名称"}<Input value={draft.name} maxLength={150} disabled={saving} onChange={(event) => update({ name: event.target.value })} /></label>
        </>}
        <div><Typography.Text>风险等级</Typography.Text><br />
          <Select aria-label="风险等级" options={riskOptions} value={draft.risk} onChange={(risk) => update({ risk })} disabled={saving} style={{ width: "100%" }} /></div>
        <div><Typography.Text>准入策略</Typography.Text><br />
          <Select aria-label="准入策略" options={decisionOptions} value={draft.decision} onChange={(decision) => update({ decision })} disabled={saving} style={{ width: "100%" }} /></div>
        <label>本次评估或变更理由<Input placeholder="例如：验收期间暂停文件外发；不要填写凭据或业务数据" value={draft.reason}
          maxLength={240} showCount disabled={saving} onChange={(event) => update({ reason: event.target.value })} /></label>
        {draft.decision === "deny" ? <Alert type="warning" showIcon title="保存后适用于当前后端存储覆盖的所有工作区和调用主体。" /> :
          <Typography.Text type="secondary">仍须满足既有白名单、主体授权及审批，本操作不会新增权限。</Typography.Text>}
      </Space>}
    </Modal>
  </Card>;
}
