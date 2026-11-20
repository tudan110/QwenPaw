import { useEffect, useState } from "react";
import { Alert, Button, Card, Input, Select, Space, Table, Tag } from "antd";
import portalManifest from "../../../package.json";
import type { McpClientInfo } from "../../api/mcp";
import { skillsApi, type WorkspaceSkillSummary } from "../../api/skills";
import { inoeSettingsApi } from "../../api/settings";
import { modelsApi } from "../../api/models";

export const dependencyKind = "第三方依赖";
export type ComponentRow = {
  key: string; name: string; kind: string; usage: string; access: string; data: string;
  risk: string; state: string; version: string; source: string;
};
interface ToolInfo { name: string; description: string; enabled: boolean }
interface PluginInfo { id: string; name: string; description: string; version: string; enabled: boolean; loaded: boolean }
interface DependencyReport { items: { name: string; declared: string; installed: string | null }[]; available: boolean }
const apiBase = (import.meta.env.VITE_COPAW_API_BASE_URL || "/copaw-api/api").replace(/\/$/, "");
async function getConfiguration<T>(path: string, signal: AbortSignal, workspace?: string): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, { signal, headers: workspace ? { "X-Agent-Id": workspace } : undefined });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
const create = (key: string, name: string, kind: string, usage: string, access: string, data: string,
  state: string, source: string, version = "—", risk = "待评估"): ComponentRow =>
  ({ key, name, kind, usage, access, data, risk, state, version, source });
const frontendDeps = Object.entries(portalManifest.dependencies).map(([name, version]) => create(
  `frontend:${name}`, name, dependencyKind, "Portal 前端直接依赖", "随构建引入，无独立调用授权",
  "按宿主功能，待核查", "构建声明", "Portal package.json", version,
));

export function ComponentInventory({ onRegister, registeredScope }: {
  onRegister: (row: ComponentRow, target: "supply" | "scan" | "scope") => void;
  registeredScope: ReadonlyMap<string, { access?: string; risk?: string; data?: string }>;
}) {
  const [skills, setSkills] = useState<WorkspaceSkillSummary[]>([]);
  const [globalRows, setGlobalRows] = useState<ComponentRow[]>([]);
  const [agentRows, setAgentRows] = useState<ComponentRow[]>([]);
  const [globalFailures, setGlobalFailures] = useState<string[]>([]);
  const [agentFailures, setAgentFailures] = useState<string[]>([]);
  const [globalLoading, setGlobalLoading] = useState(true);
  const [agentLoading, setAgentLoading] = useState(true);
  const [agent, setAgent] = useState("default");
  const [kind, setKind] = useState("全部");
  const [query, setQuery] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    setGlobalLoading(true);
    const connection = inoeSettingsApi.get().then((payload) => create(
      "integration:inoe", "智观平台网关", "连接器", "承载告警、监控与工单业务对接", "按各业务调用的现有凭据与策略",
      "告警、指标、工单；实际可见范围由上游决定", payload.effective.inoe_api_base_url ? "已登记连接配置" : "未登记网关地址",
      "平台设置", "—"));
    const plugins = getConfiguration<PluginInfo[]>("/plugins", signal).then((items) => items.map((item) => create(
      `plugin:${item.id}`, item.name || item.id, "插件", item.description || "服务端插件",
      "由插件及宿主配置决定", "待核查", item.loaded ? (item.enabled ? "已加载" : "已禁用") : "发现清单，未确认加载",
      "插件列表", item.version || "—")));
    const backendDeps = getConfiguration<DependencyReport>("/tools/component-dependencies", signal).then((report) => {
      if (!report.available) throw new Error("backend distribution metadata unavailable");
      return report.items.map((item) => create(`backend:${item.name}`, item.name, dependencyKind, "QwenPaw 后端直接依赖",
        "随服务引入，无独立调用授权", "按宿主功能，待核查", item.installed ? "检测到安装元数据" : "未检测到安装版本",
        `后端发行包声明 ${item.declared || "未限制版本"}`, item.installed || "—"));
    });
    const workspaces = skillsApi.listWorkspaceSkills(signal);
    void Promise.allSettled([plugins, connection, backendDeps, workspaces] as const).then(([p, c, d, w]) => {
      if (signal.aborted) return;
      setGlobalRows([...(p.status === "fulfilled" ? p.value : []), ...(c.status === "fulfilled" ? [c.value] : []), ...(d.status === "fulfilled" ? d.value : [])]);
      setSkills(w.status === "fulfilled" ? w.value : []);
      setGlobalFailures([[p, "插件"], [c, "平台连接器"], [d, "后端依赖"], [w, "工作区技能"]].flatMap(([result, label]) => (result as PromiseSettledResult<unknown>).status === "rejected" ? [String(label)] : []));
      setGlobalLoading(false);
    });
    return () => controller.abort();
  }, [refresh]);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    setAgentLoading(true);
    setAgentRows([]);
    setAgentFailures([]);
    const tools = getConfiguration<ToolInfo[]>("/tools", signal, agent).then((items) => items.map((item) => create(
      `tool:${agent}:${item.name}`, item.name, "工具", item.description || "内建工具", "工作区启用状态 + 运行时工具策略",
      "按工具与任务，待核查", item.enabled ? "配置启用" : "配置禁用", `工具配置 / ${agent}`)));
    const mcp = getConfiguration<McpClientInfo[]>("/mcp", signal, agent).then((items) => items.flatMap((item) => {
      const effect = item.access_summary?.default_effect;
      const access = effect ? `默认${{ allow: "允许", ask: "询问", deny: "拒绝" }[effect]} · ${item.access_summary?.overrides_count ?? 0} 条覆盖规则` : "未返回默认权限";
      const state = item.enabled ? "配置启用" : "配置禁用";
      const source = `MCP 配置 / ${agent}`;
      return [create(`mcp:${agent}:${item.key}`, item.name || item.key, "协议服务（MCP）", item.description || `MCP 服务（${item.transport}）`,
        access, "由工具和上游授权决定，待核查", state, source), ...(item.tools || []).map((tool) => create(
        `mcp-tool:${agent}:${item.key}:${tool}`, `${item.name || item.key} / ${tool}`, "工具", "MCP 配置中的工具白名单条目",
        "工具覆盖规则在 MCP 策略中管理", "由上游权限决定，待核查", state, source))];
    }));
    const model = modelsApi.getActiveModels({ scope: "effective", agent_id: agent }).then((result) => {
      const item = result.active_llm;
      return item?.model ? [create(`model:${agent}:${item.provider_id}:${item.model}`, item.model, "模型", "当前工作区对话模型配置",
        "由工作区及模型供应商配置决定", "可能接收当前对话的模型输入，按任务核查", "已配置", `模型设置 / ${agent}`, "—")] : [];
    });
    void Promise.allSettled([tools, mcp, model]).then((results) => {
      if (signal.aborted) return;
      setAgentRows(results.flatMap((result) => result.status === "fulfilled" ? result.value : []));
      setAgentFailures(results.flatMap((result, index) => result.status === "rejected" ? [["工具", "MCP", "模型"][index]] : []));
      setAgentLoading(false);
    });
    return () => controller.abort();
  }, [agent, refresh]);

  const workspaces = Array.from(new Map([["default", "default"], ...skills.map((item) => [item.agent_id, item.agent_name || item.agent_id] as const)]));
  const workspaceSkills = skills.find((item) => item.agent_id === agent)?.skills ?? [];
  const rows = [
    ...workspaceSkills.map((item) => create(`skill:${agent}:${item.name}`, item.name, "技能", item.description || "工作区技能",
      item.channels?.length ? `渠道范围：${item.channels.join("、")}` : "工作区启用状态；未返回渠道范围",
      "按技能调用的工具及上游权限，待核查", item.enabled ? "配置启用" : "配置禁用", `工作区技能 / ${agent}`, item.version_text || "—")),
    ...agentRows, ...globalRows, ...frontendDeps,
  ];
  const visible = rows.filter((row) => (kind === "全部" || row.kind === kind) &&
    `${row.name} ${row.usage} ${row.source}`.toLowerCase().includes(query.trim().toLowerCase()));
  const failures = [...globalFailures, ...agentFailures];
  return <Space orientation="vertical" size="middle" className="gov-stack">
    <Alert type="info" showIcon title="组件目录与调用边界"
      description="按工作区读取工具、技能、MCP 和模型配置，汇总插件、平台连接器与直接依赖。启用状态仅代表配置，权限覆盖、实际调用结果和完整部署物料以对应执行策略和发布清单为准。登记权限范围不会改变实际调用权限。" />
    {failures.length > 0 && <Alert type="warning" showIcon title={`以下来源不可用：${failures.join("、")}`} description="未将无法读取的来源计为未接入。" />}
    <Card size="small"><Space wrap>
      <span>工作区</span><Select aria-label="工作区" value={agent} onChange={setAgent} options={workspaces.map(([value, label]) => ({ value, label }))} style={{ minWidth: 140 }} />
      <span>组件类别</span><Select aria-label="组件类别" value={kind} onChange={setKind} options={["全部", "工具", "技能", "插件", "连接器", "协议服务（MCP）", dependencyKind, "模型"].map((value) => ({ value }))} style={{ minWidth: 145 }} />
      <Input.Search placeholder="搜索名称、用途或来源" allowClear value={query} onChange={(e) => setQuery(e.target.value)} />
      <Button onClick={() => setRefresh((value) => value + 1)} loading={globalLoading || agentLoading}>刷新目录</Button>
    </Space></Card>
    <Table<ComponentRow> bordered size="small" rowKey="key" dataSource={visible} pagination={{ pageSize: 8, showSizeChanger: false }} scroll={{ x: 1030 }}
      locale={{ emptyText: globalLoading || agentLoading ? "正在读取来源…" : "当前筛选没有可展示的组件" }} columns={[
        { title: "组件 / 来源", width: 188, render: (_, row) => <><strong>{row.name}</strong><br /><small>{row.source}</small></> },
        { title: "类别 / 版本", width: 138, render: (_, row) => <><Tag>{row.kind}</Tag><br />{row.version}</> },
        { title: "功能用途", dataIndex: "usage", width: 190, ellipsis: true },
        { title: "调用权限 / 数据范围", width: 245, render: (_, row) => <>{row.access}<br /><small>{row.data}</small>{registeredScope.has(row.key) && <><br /><Tag color="blue">登记：{registeredScope.get(row.key)?.access}</Tag><small>{registeredScope.get(row.key)?.data}</small></>}</> },
        { title: "状态 / 风险", width: 138, render: (_, row) => <>{row.state}<br /><Tag color="orange">{registeredScope.has(row.key) ? `登记风险：${registeredScope.get(row.key)?.risk}` : row.risk}</Tag></> },
        { title: "登记台账", width: 200, render: (_, row) => <Space size={4} wrap><Button type="link" size="small" onClick={() => onRegister(row, "scope")}>权限范围</Button><Button type="link" size="small" onClick={() => onRegister(row, "supply")}>变更</Button><Button type="link" size="small" onClick={() => onRegister(row, "scan")}>扫描</Button></Space> },
      ]} />
  </Space>;
}
