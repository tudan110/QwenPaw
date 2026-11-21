import { useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Descriptions, Empty, Select, Space, Table, Tag } from "antd";
import { ReloadOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import {
  componentGovernanceApi as api, type Change, type Changes, type ChangeView,
  type LocalMode, type LocalPolicy, type ScanReport, type ScanRow, type ScanStatus,
} from "../../api/componentGovernance";

const kindLabels: Record<string, string> = {
  provider: "模型提供商", model: "模型", skill: "技能", mcp: "MCP", config: "配置",
  prompt: "提示词 / 工作区文档", local: "本地部署策略", dependency: "依赖", plugin: "插件 / 外部服务",
};
const actionLabels: Record<string, string> = { add: "新增", remove: "移除", update: "修改", enable: "启用", disable: "停用" };
const fieldLabels: Record<string, string> = {
  provider: "提供商", provider_id: "提供商", model: "模型", api_key: "API 密钥", custom_headers: "请求头",
  base_url: "服务地址", name: "名称", content: "文件内容", enabled: "启用状态", version: "版本",
  security: "安全规则", running: "运行配置", approval_level: "审批等级", llm_routing: "模型路由",
  system_prompt_files: "系统提示词文件", tools: "工具编排", credentials: "凭据", endpoint: "连接配置",
  policy: "准入策略", installed: "已安装", metadata: "技能内容 / 元数据", access_mode: "访问模式",
};
const fieldName = (field: string) => fieldLabels[field] || field;
const displayTime = (date: string) => new Date(date).toLocaleString("zh-CN", { hour12: false });
const errorText = (error: unknown) => error instanceof Error ? error.message : "请求未完成，请重试。";
const statusLabels: Record<ScanStatus, [string, string]> = {
  clear: ["未发现问题", "success"], findings: ["有发现 · 待处置", "error"],
  incomplete: ["检查未完成", "warning"], not_covered: ["未覆盖", "default"], not_applicable: ["不适用", "default"],
};
const remediation: Record<string, string> = {
  skill: "核对报告中的规则和业务用途；必要时在技能管理停用或修订后复扫。",
  mcp: "在 MCP 管理修正连接或准入配置；不可信项先停用，再复扫。",
  model: "核对模型提供商的地址和凭据设置，修正后复扫。",
  dependency: "按公告升级或替换受影响版本，再用部署后的运行环境复扫。",
};

function summaryText(values: Change["before"]) {
  if (!values) return "未配置 / 不存在";
  return Object.entries(values).map(([k, v]) => `${fieldName(k)}：${typeof v === "boolean" ? (v ? "启用" : "停用") : v}`).join("；") || "仅记录变更，不公开内容";
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
    <Alert type="info" showIcon title={view === "supply" ? "实际保存后自动记录，无需登记" : "实际配置变更自动记录"}
      description={view === "supply" ? "本页反映模型、技能、MCP 和受管插件的变更；不代表兼容性、来源或上线审批已通过。可在「扫描与处置」检查当前状态。"
        : "记录主体、范围、时间和可公开差异，不记录密钥、请求头、提示词原文。运行时重载及回退不以保存成功为证明；回退需在原配置入口操作。"} />
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
          { title: "变更对象", width: 230, render: (_, r) => <div className="gov-cell"><strong>{r.target}</strong><span className="gov-secondary">{kindLabels[r.kind] || r.kind} · {r.scope}</span></div> },
          { title: "操作", width: 85, render: (_, r) => <Tag>{actionLabels[r.action] || r.action}</Tag> },
          { title: "变更主体", dataIndex: "subject", width: 145 },
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
  const active = useRef<AbortController | null>(null);
  const load = (run = false) => {
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
  const rows = report?.rows || [];
  return <div className="gov-flow">
    <Alert showIcon type="info" title="一键检查当前部署" description="检查技能静态规则、模型及 MCP 配置；启用 OSV 时按 Python 实际安装版本查已知公告。未接入或未完成的项目单独标明。不执行技能、不连接 MCP，也不会自动停用组件。" />
    {error && <Alert type="error" showIcon title={error} description={report ? "下方仍显示上一次已保存报告。" : undefined} />}
    <section className="gov-surface" aria-label="扫描结果">
      <div className="gov-toolbar">
        <Button type="primary" icon={<SafetyCertificateOutlined />} loading={busy} onClick={() => load(true)}>一键扫描</Button>
        <Button icon={<ReloadOutlined />} disabled={busy} onClick={() => load()}>刷新报告</Button>
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
          { title: "检查对象", width: 220, render: (_, r) => <div className="gov-cell"><strong>{r.name}</strong><span className="gov-secondary">{kindLabels[r.kind] || r.kind} · {r.scope}</span></div> },
          { title: "结果", width: 135, render: (_, r) => <Tag color={statusLabels[r.status][1]}>{statusLabels[r.status][0]}</Tag> },
          { title: "说明 / 发现项", width: 290, render: (_, r) => <div className="gov-cell"><span>{r.detail}</span>{r.findings.map((f, i) => <span key={i}>{f}</span>)}</div> },
          { title: "建议处置", render: (_, r) => r.status === "findings" ? remediation[r.kind] || "由责任人核查后复扫。" : "—" },
        ]} />
    </section>
  </div>;
}

export function LocalAccessPanel() {
  const [policy, setPolicy] = useState<LocalPolicy>();
  const [mode, setMode] = useState<LocalMode>("managed");
  const [busy, setBusy] = useState(true);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const active = useRef<AbortController | null>(null);
  const load = (save?: LocalMode) => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setNotice("");
    setError("");
    (save ? api.saveLocalPolicy(save, controller.signal) : api.localPolicy(controller.signal))
      .then((data) => {
        if (controller.signal.aborted) return;
        setPolicy(data); setMode(data.mode);
        if (save) setNotice("访问策略已保存至服务端。");
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
      <Space wrap>
        <Select<LocalMode> aria-label="本地资源访问策略" style={{ minWidth: 255 }} disabled={!policy || busy} value={policy ? mode : undefined} placeholder="读取策略…"
          onChange={setMode} options={[{ value: "managed", label: "检测到受管本地运行时严格管控" }, { value: "deny", label: "禁止受管本地运行与下载" }]} />
        <Button type="primary" loading={busy} disabled={!policy || policy.mode === mode} onClick={() => load(mode)}>保存策略</Button>
        <Button disabled={busy} icon={<ReloadOutlined />} onClick={() => load()}>刷新检测</Button>
      </Space>
    </Card>
    {policy && !policy.filesystem_supported && <Alert type="warning" showIcon title="当前宿主未实现本地模型文件 ACL 校验；受管启动和下载会被拒绝。" />}
    {policy?.external_local_detected && <Alert type="warning" showIcon title="检测到全局默认模型使用外部本地提供商。" description="Ollama、LM Studio 等外部进程的权限由其部署方实施；本页不将其标为已受控。" />}
    <Descriptions bordered column={1} size="small" items={[
      { key: "model", label: "模型文件", children: "仅加载服务账户自有受管目录中的普通模型文件；加载前设为所有者只读，拒绝硬链接或越界文件。" },
      { key: "cache", label: "缓存及临时文件", children: "受管存储目录仅服务账户可进入；本地推理不输出请求日志，普通文件预览不得访问该目录。" },
      { key: "interface", label: "推理接口", children: "固定回环监听；使用不落盘的内部凭据，启动时检验无凭据访问被拒绝、合法凭据可用。健康检查不承载业务数据。" },
      { key: "coverage", label: "适用范围", children: "dev-81 样品未启用端侧模型。此策略针对 QwenPaw 内置 llama.cpp，不更改现有远端提供商或替代独立主机权限管理。" },
    ]} />
  </div>;
}

const flows = [
  ["智观 → Portal / QwenPaw", "身份标识、角色、会话凭据", "服务端验证身份；仅在授权链路传递凭据，不展示原文。", "登录、访问控制证据"],
  ["Portal ⇄ QwenPaw 智能体", "提问、附件引用、任务状态、回复", "按身份绑定会话及访问工作区；按会话返回结果。", "会话号 / 调用追踪"],
  ["QwenPaw ⇄ 模型提供商", "任务输入、必要上下文、工具结果、模型响应", "按配置路由；调用凭据与输入分离。任务内容可能含业务数据，需按部署核验出域和脱敏。", "模型配置变更 / 运行追踪"],
  ["QwenPaw ⇄ MCP / 智观业务接口", "工具名、目标资源、请求参数、结构化结果", "检查调用准入和授权范围；凭据仅供对应上游使用。", "调用准入 / 工具审计与追踪"],
  ["受控资料 → 审查 / 脱敏 → 共享知识库 ⇄ 智能体", "资料、审核记录、发布副本、检索片段", "个人资料与共享副本隔离，按授权发布；检索读取授权范围内的结果。", "资料操作 / 发布记录"],
];

export function ComponentDataFlows() {
  return <div className="gov-flow">
    <Alert type="info" showIcon title="部署链路说明，不是实时抓包" description="用于定位数据类型、方向和保护措施。核验具体请求时，请按同一会话或操作编号对照调用审计、运行追踪及资料操作记录；不展示敏感原文。" />
    <Table className="gov-table" size="small" rowKey="flow" pagination={false} scroll={{ x: 930 }}
      dataSource={flows.map(([flow, data, handling, evidence]) => ({ flow, data, handling, evidence }))}
      columns={[
        { title: "数据流向", dataIndex: "flow", width: 250 }, { title: "数据类型", dataIndex: "data", width: 205 },
        { title: "处理方式与保护", dataIndex: "handling", width: 320 }, { title: "追溯入口", dataIndex: "evidence" },
      ]} />
  </div>;
}
