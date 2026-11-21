import { useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Descriptions, Empty, Popconfirm, Select, Space, Switch, Table, Tag } from "antd";
import { ReloadOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import {
  componentGovernanceApi as api, type Change, type Changes, type ChangeView,
  type LocalMode, type LocalPolicy, type ScanReport, type ScanRow, type ScanStatus,
} from "../../api/componentGovernance";

const kindLabels: Record<string, string> = {
  privacy_policy: "敏感数据策略",
  provider: "模型提供商", model: "模型", skill: "技能", mcp: "MCP", config: "配置",
  prompt: "提示词 / 工作区文档", local: "本地部署策略", dependency: "依赖", plugin: "插件 / 外部服务",
};
const actionLabels: Record<string, string> = { add: "新增", remove: "移除", update: "修改", enable: "启用", disable: "停用" };
const fieldLabels: Record<string, string> = {
  builtin: "内置识别规则", custom_fields: "自定义敏感字段", chat_input: "对话输入", model_context: "模型上下文",
  documents: "受控资料", knowledge: "知识库入库", query_results: "业务查询与工具结果",
  exports: "业务与资料导出", logs: "应用日志", cache: "运行缓存", debug: "调试与调用追踪",
  provider: "提供商", provider_id: "提供商", model: "模型", api_key: "API 密钥", custom_headers: "请求头",
  base_url: "服务地址", name: "名称", content: "文件内容", enabled: "启用状态", version: "版本",
  security: "安全规则", running: "运行配置", approval_level: "审批等级", llm_routing: "模型路由",
  system_prompt_files: "系统提示词文件", tools: "工具编排", credentials: "凭据", endpoint: "连接配置",
  policy: "准入策略", installed: "已安装", metadata: "技能内容 / 元数据", access_mode: "访问模式",
  allow_downloads: "允许下载", isolated: "隔离状态",
};
const fieldName = (field: string) => fieldLabels[field] || (/[a-z_]/i.test(field) ? "其他配置" : field);
const publicLabels: Record<string, string> = {
  gateway: "智观AI", global: "全局", fault: "故障分析专家", order: "工单处置专员", query: "数据分析专家",
  resource: "资产管理专员", inspection: "运维巡检专员", knowledge: "知识库助手", operator: "操作助手",
  "qwenpaw-local": "受管本地模型", "Portal / Console 前端与操作系统依赖": "智观AI前端与操作系统依赖",
  "智观 Paw": "智观AI", QwenPaw: "智观AI",
};
const publicLabel = (value: string) => publicLabels[value] ?? value;
const workspaceName = (row: { scope: string; scope_name?: string }) => row.scope_name ||
  (publicLabels[row.scope] ?? (/[\u3400-\u9fff]/.test(row.scope) ? row.scope : "数字员工"));
const displayTime = (date: string) => new Date(date).toLocaleString("zh-CN", { hour12: false });
const errorText = (error: unknown) => error instanceof Error ? error.message : "请求未完成，请重试。";
const statusLabels: Record<ScanStatus, [string, string]> = {
  clear: ["未发现问题", "success"], findings: ["有发现", "error"],
  incomplete: ["检查未完成", "warning"], not_covered: ["未覆盖", "default"], not_applicable: ["不适用", "default"],
};
const remediation: Record<string, string> = {
  skill: "核对报告中的规则和业务用途；必要时在技能管理停用或修订后复扫。",
  mcp: "在 MCP 管理修正连接或准入配置；不可信项先停用，再复扫。",
  model: "在模型配置更换不安全的接口；请先核对依赖该模型的数字员工，切换后复扫。",
  dependency: "按公告升级或替换受影响版本，再用部署后的运行环境复扫。",
};

function summaryText(values: Change["before"]) {
  if (!values) return "未配置 / 不存在";
  return Object.entries(values).map(([k, v]) => `${fieldName(k)}：${typeof v === "boolean" ? (v ? "启用" : "停用") : typeof v === "string" ? publicLabel(v) : v}`).join("；") || "仅记录变更，不公开内容";
}

export function ComponentChangePanel({ view }: { view: ChangeView }) {
  const [data, setData] = useState<Changes>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setBusy(true);
    setError("");
    api.changes(view, (page - 1) * 20, controller.signal)
      .then(setData).catch((e) => { if (!controller.signal.aborted) setError(errorText(e)); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [view, page, refresh]);
  return <div className="gov-flow">
    {data?.write_warning && <Alert type="warning" showIcon title="发现审计写入失败，记录可能不完整，请管理员检查服务日志。" />}
    {error && <Alert type="error" showIcon title={error} />}
    <section className="gov-surface" aria-label="自动变更记录">
      <div className="gov-toolbar"><Button icon={<ReloadOutlined />} loading={busy} onClick={() => setRefresh((n) => n + 1)}>刷新记录</Button></div>
      <Table<Change> className="gov-table" size="small" rowKey="id" loading={busy} scroll={{ x: 820 }}
        dataSource={error ? [] : data?.records || []}
        pagination={{ current: page, total: data?.total, pageSize: 20, showSizeChanger: false, onChange: setPage, showTotal: (n) => `共 ${n} 条` }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={error ? "未取得记录" : "尚无自动记录。只记录接入审计后由受管配置入口保存的变更。"} /> }}
        columns={[
          { title: "记录时间", width: 165, render: (_, r) => displayTime(r.timestamp) },
          { title: "变更对象", width: 230, render: (_, r) => <div className="gov-cell"><strong>{publicLabel(r.target)}</strong><span className="gov-secondary">{kindLabels[r.kind] || "组件"} · {workspaceName(r)}</span></div> },
          { title: "操作", width: 85, render: (_, r) => <Tag>{actionLabels[r.action] || r.action}</Tag> },
          { title: "操作账号", width: 145, render: (_, r) => r.subject.replace(/^(?:inoe|local):/, "") },
          { title: "变化项", render: (_, r) => r.fields.map(fieldName).join("、") || "—" },
        ]}
        expandable={{ expandedRowRender: (r) => <Descriptions column={1} size="small" items={[
          { key: "before", label: "变更前", children: summaryText(r.before) },
          { key: "after", label: "变更后", children: summaryText(r.after) },
          { key: "state", label: "证据范围", children: "已写入配置；未自动核验审批、兼容性或运行时生效。" },
        ]} /> }} />
    </section>
  </div>;
}

export function ComponentScanPanel() {
  const [report, setReport] = useState<ScanReport | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [filter, setFilter] = useState<ScanStatus | "all">("all");
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState<number>();
  const active = useRef<AbortController | null>(null);
  const load = (run = false) => {
    setNotice("");
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError("");
    (run ? api.scan(controller.signal) : api.scanReport(controller.signal))
      .then((data) => { if (!controller.signal.aborted) setReport(data.report); })
      .catch((e) => { if (!controller.signal.aborted) setError(errorText(e)); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
  };
  useEffect(() => { load(); return () => active.current?.abort(); }, []);
  async function dispose(index: number) {
    if (!report || busy || pending !== undefined) return;
    const controller = new AbortController();
    active.current = controller;
    setPending(index);
    setError("");
    setNotice("");
    try {
      const result = await api.disposition(report.checked_at, index, controller.signal);
      if (!controller.signal.aborted) { setReport(result.report); setNotice(result.message); }
    } catch (failure) {
      if (!controller.signal.aborted) setError(errorText(failure));
    } finally {
      if (!controller.signal.aborted) setPending(undefined);
    }
  }
  const rows = report?.rows || [];
  return <div className="gov-flow">
    {error && <Alert type="error" showIcon title={error} description={report ? "请刷新报告以核对当前处置状态。" : undefined} />}
    {notice && <Alert type="success" showIcon title={notice} />}
    <section className="gov-surface" aria-label="扫描结果">
      <div className="gov-toolbar">
        <Button type="primary" icon={<SafetyCertificateOutlined />} loading={busy} disabled={pending !== undefined} onClick={() => load(true)}>一键扫描</Button>
        <Button icon={<ReloadOutlined />} disabled={busy || pending !== undefined} onClick={() => load()}>刷新报告</Button>
        <Select aria-label="扫描结果筛选" style={{ minWidth: 143 }} value={filter} onChange={setFilter}
          options={[{ value: "all", label: "全部状态" }, ...Object.entries(statusLabels).map(([value, [label]]) => ({ value, label }))]} />
      </div>
      {report && <Space wrap size="small" style={{ marginBlock: 12 }}>
        <span>扫描完成时间：{displayTime(report.checked_at)}</span>
        {Object.entries(statusLabels).map(([status, [label, color]]) => <Tag key={status} color={color}>{label} {rows.filter((r) => r.status === status).length}</Tag>)}
      </Space>}
      <Table<ScanRow> className="gov-table" size="small" rowKey={(r) => `${r.kind}:${r.scope}:${r.name}`}
        dataSource={filter === "all" ? rows : rows.filter((r) => r.status === filter)} scroll={{ x: 890 }}
        pagination={{ pageSize: 12, showSizeChanger: false }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={busy ? "正在读取或执行检查…" : report ? "没有匹配状态的项目。" : "暂无扫描报告，点击「一键扫描」检查当前部署。"} /> }}
        columns={[
          { title: "检查对象", width: 220, render: (_, r) => <div className="gov-cell"><strong>{publicLabel(r.name)}</strong><span className="gov-secondary">{kindLabels[r.kind] || "组件"} · {workspaceName(r)}</span></div> },
          { title: "结果", width: 135, render: (_, r) => <Tag color={statusLabels[r.status][1]}>{statusLabels[r.status][0]}</Tag> },
          { title: "说明 / 发现项", width: 290, render: (_, r) => <div className="gov-cell"><span>{r.detail}</span>{r.findings.map((f, i) => <span key={i}>{f}</span>)}</div> },
          { title: "处置", width: 250, render: (_, r) => {
            if (r.status !== "findings") return "—";
            const action = r.action;
            if (!action) return remediation[r.kind] || "由责任人核查后复扫。";
            const skill = action.kind === "disable_skill";
            if (action.done) return <div className="gov-cell"><Tag color="gold">{skill ? "已停用" : "已隔离"}</Tag>
              <span className="gov-secondary">修复并复扫后，可在{skill ? "技能管理重新启用" : "调用准入解除隔离"}。</span></div>;
            return <Popconfirm title={skill ? "停用这项技能？" : "隔离这个连接？"}
              description={skill ? "只停用当前数字员工的技能，不删除文件；不会中断已经开始的任务。"
                : "此部署所有同名连接的后续调用都将被拒绝，不删除连接配置，也不中断已发出的请求。"}
              okText={skill ? "确认停用" : "确认隔离"} cancelText="取消" okButtonProps={{ danger: true }}
              onConfirm={() => dispose(action.index)}>
              <Button danger size="small" disabled={busy || pending !== undefined} loading={pending === action.index}>
                {skill ? "停用技能" : "隔离连接"}
              </Button>
            </Popconfirm>;
          } },
        ]} />
    </section>
  </div>;
}

export function LocalAccessPanel() {
  const [policy, setPolicy] = useState<LocalPolicy>();
  const [mode, setMode] = useState<LocalMode>("managed");
  const [downloads, setDownloads] = useState(true);
  const [busy, setBusy] = useState(true);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const active = useRef<AbortController | null>(null);
  const load = (action: "save" | "refresh" | "stop" = "refresh") => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setNotice("");
    setError("");
    (action === "save" ? api.saveLocalPolicy(mode, downloads, controller.signal) :
      action === "stop" ? api.stopLocal(controller.signal) : api.localPolicy(controller.signal))
      .then((data) => {
        if (controller.signal.aborted) return;
        setPolicy(data); setMode(data.mode); setDownloads(data.allow_downloads);
        if (action === "save") setNotice("访问策略已保存，后续请求按新策略执行。");
        if (action === "stop") setNotice("受管本地推理已停止。");
      })
      .catch((e) => { if (!controller.signal.aborted) setError(errorText(e)); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
  };
  useEffect(() => { load(); return () => active.current?.abort(); }, []);
  return <div className="gov-flow">
    {error && <Alert type="error" showIcon title={error} />}
    {notice && <Alert type="success" showIcon title={notice} />}
    <Card size="small" title="受管本地模型资源访问" extra={policy && <Tag color={policy.running ? (policy.authenticated ? "green" : "red") : "default"}>
      {policy.running ? (policy.authenticated ? "受管运行 · 已验证接口鉴权" : "运行中 · 未验证鉴权") : "未检测到受管本地推理运行"}</Tag>}>
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <p className="gov-secondary">在此设置是否允许运行本地模型，以及是否允许下载新模型和运行组件。</p>
        <label className="gov-cell">运行权限
          <Select<LocalMode> aria-label="本地模型运行权限" style={{ maxWidth: 360 }} disabled={!policy || busy}
            value={policy ? mode : undefined} placeholder="读取策略…" onChange={setMode}
            options={[{ value: "managed", label: "允许受管运行（强制访问保护）" }, { value: "deny", label: "禁止受管运行与下载" }]} />
        </label>
        <Space wrap>
          <Switch aria-label="允许下载本地模型与运行组件" checked={mode !== "deny" && downloads}
            disabled={!policy || busy || mode === "deny"} onChange={setDownloads} />
          <span>允许下载新模型与运行组件</span>
        </Space>
        <span className="gov-secondary">关闭下载后，已下载且通过权限检查的模型仍可运行。访问保护不能关闭。</span>
        <Space wrap>
          <Button type="primary" loading={busy} disabled={!policy || (policy.mode === mode && policy.allow_downloads === downloads)} onClick={() => load("save")}>保存策略</Button>
          <Button disabled={busy} icon={<ReloadOutlined />} onClick={() => load()}>刷新检测</Button>
          {policy?.running && <Popconfirm title="停止受管本地推理？" description="依赖本地模型的任务可能暂时无法运行。"
            okText="确认停止" cancelText="取消" okButtonProps={{ danger: true }} onConfirm={() => load("stop")}>
            <Button danger disabled={busy}>停止本地推理</Button>
          </Popconfirm>}
        </Space>
      </Space>
    </Card>
    {policy && !policy.filesystem_supported && <Alert type="warning" showIcon title="当前环境无法验证本地模型文件权限，系统会拒绝启动和下载。" />}
    {policy?.external_local_detected && <Alert type="warning" showIcon title="检测到全局默认模型使用外部本地提供商。" description="外部本地模型由其部署方管理，本页策略不覆盖外部进程。" />}
    <Descriptions bordered column={1} size="small" items={[
      { key: "model", label: "模型文件", children: "仅加载服务账户自有受管目录中的普通模型文件；加载前设为所有者只读，拒绝硬链接或越界文件。" },
      { key: "cache", label: "缓存及临时文件", children: "受管存储目录仅服务账户可进入；本地推理不输出请求日志，普通文件预览不得访问该目录。" },
      { key: "interface", label: "推理接口", children: "仅允许本机连接；服务启动时验证鉴权，未授权的请求会被拒绝。" },
      { key: "coverage", label: "适用范围", children: "此策略适用于智观AI受管的本地模型，不更改远端提供商配置，也不替代独立主机的权限管理。" },
    ]} />
  </div>;
}

const flows = [
  ["单点登录 → 智观AI", "身份标识、角色、会话凭据", "服务端验证身份；仅在授权链路传递凭据，不展示原文。", "登录、访问控制证据"],
  ["用户 ⇄ 智观AI", "提问、附件引用、任务状态、回复", "按身份绑定会话及访问工作区；按会话返回结果。", "会话号 / 调用追踪"],
  ["智观AI ⇄ 模型提供商", "任务输入、必要上下文、工具结果、模型响应", "按配置路由；调用凭据与输入分离。任务内容可能含业务数据，需按部署核验出域和脱敏。", "模型配置变更 / 运行追踪"],
  ["智观AI ⇄ MCP / 业务接口", "工具名、目标资源、请求参数、结构化结果", "检查调用准入和授权范围；凭据仅供对应上游使用。", "调用准入 / 工具审计与追踪"],
  ["受控资料 → 审查 / 脱敏 → 共享知识库 ⇄ 智观AI", "资料、审核记录、发布副本、检索片段", "个人资料与共享副本隔离，按授权发布；检索读取授权范围内的结果。", "资料操作 / 发布记录"],
];

export function ComponentDataFlows() {
  return <div className="gov-flow">
    <Table className="gov-table" size="small" rowKey="flow" pagination={false} scroll={{ x: 930 }}
      dataSource={flows.map(([flow, data, handling, evidence]) => ({ flow, data, handling, evidence }))}
      columns={[
        { title: "数据流向", dataIndex: "flow", width: 250 }, { title: "数据类型", dataIndex: "data", width: 205 },
        { title: "处理方式与保护", dataIndex: "handling", width: 320 }, { title: "追溯入口", dataIndex: "evidence" },
      ]} />
  </div>;
}
