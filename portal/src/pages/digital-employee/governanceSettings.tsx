import { useState } from "react";
import {
  ApartmentOutlined, AuditOutlined, BranchesOutlined, DatabaseOutlined, DeploymentUnitOutlined,
  FileSearchOutlined, LockOutlined, SafetyCertificateOutlined, SettingOutlined, SwapOutlined,
} from "@ant-design/icons";
import { Button, Card, Collapse, ConfigProvider, Descriptions, Form, Input, Select, Space, Tabs, Tag, theme, type TabsProps } from "antd";
import { SensitiveDataGovernancePanel } from "./sensitiveDataGovernancePanel";
import { ComponentAdmissionPanel } from "./componentAdmissionPanel";
import { ComponentInventory, type ComponentRow } from "./componentInventory";
import { field, Ledger, optional, getLedgerRows, governanceAccount, type Values } from "./governanceLedger";
import { ComponentChangePanel, ComponentDataFlows, ComponentScanPanel, LocalAccessPanel } from "./componentGovernancePanels";
import { previewSensitiveData, syntheticData } from "./governanceFacts";
import "./portalGovernance.css";

const scopeFields = [field("component", "组件名称"), field("workspace", "覆盖范围 / 工作区"),
  field("access", "登记调用权限", ["只读", "允许", "需人工确认", "拒绝", "按上游授权", "待核查"]),
  field("risk", "登记风险", ["待评估", "低", "中", "高", "严重"]), optional("data", "登记的数据访问范围", "textarea"),
  optional("reason", "评估依据及变更原因", "textarea"), { ...optional("componentId", "组件目录关联编号"), hidden: true }];

const previewFields = {
  range: "批量敏感采集须审批",
  retention: "7",
  mask: "mask",
  deletion: "到期删除（登记规则）",
  logs: "禁止原文进入日志、缓存或调试信息",
};

function SensitivePolicy({ scope }: { scope: string }) {
  const [profile, setProfile] = useState(() => {
    if (!scope) return previewFields;
    try {
      return { ...previewFields, ...JSON.parse(localStorage.getItem(`portal.governance.v1.${encodeURIComponent(scope)}.sensitive-preview`) || "{}") };
    } catch { return previewFields; }
  });
  const [notice, setNotice] = useState("");
  const apply = (values: typeof previewFields) => {
    if (!scope) return;
    setProfile(values);
    try {
      localStorage.setItem(`portal.governance.v1.${encodeURIComponent(scope)}.sensitive-preview`, JSON.stringify(values));
      setNotice("已更新规则预览");
    } catch { setNotice("已更新本页预览，但浏览器存储不可用，无法保留设置。"); }
  };
  const example = previewSensitiveData(profile.mask);
  const sampleDecision = profile.range === "禁止批量敏感采集" ? "拒绝示例采集" : "示例采集等待人工审批";
  return <Space orientation="vertical" size="middle" className="gov-stack">
    <Card size="small" title="敏感数据规则预览">
      <Form layout="vertical" initialValues={profile} onFinish={apply}>
        <div className="gov-form-grid">
          <Form.Item label="批量敏感数据采集" name="range"><Select options={["批量敏感采集须审批", "禁止批量敏感采集"].map((value) => ({ value }))} /></Form.Item>
          <Form.Item label="最长留存（天）" name="retention" rules={[{ required: true, pattern: /^(?:[1-9]\d?|[12]\d\d|3[0-5]\d|36[0-5])$/, message: "填写 1 至 365 的整数" }]}><Input type="number" min={1} max={365} /></Form.Item>
          <Form.Item label="脱敏方式" name="mask"><Select options={[{ label: "保留部分字符", value: "mask" }, { label: "移除敏感字段", value: "omit" }]} /></Form.Item>
          <Form.Item label="删除规则" name="deletion"><Select options={["到期删除（登记规则）", "到期提交人工复核（登记规则）"].map((value) => ({ value }))} /></Form.Item>
          <Form.Item className="gov-full" label="日志、缓存和调试信息" name="logs"><Select options={["禁止原文进入日志、缓存或调试信息", "结构化日志只保留事件编号，不登记业务原文"].map((value) => ({ value }))} /></Form.Item>
        </div>
        <Button type="primary" htmlType="submit" disabled={!scope}>应用到示例</Button>{notice && <span className="gov-inline-status" role="status">{notice}</span>}
      </Form>
    </Card>
    <div className="gov-preview-grid">
      <Card size="small" title="示例输入" extra={<Tag>合成数据</Tag>}>
        <pre className="gov-preview">{JSON.stringify(syntheticData, null, 2)}</pre>
      </Card>
      <Card size="small" title="脱敏预览">
        <pre className="gov-preview">{JSON.stringify(example, null, 2)}</pre>
      </Card>
    </div>
    <Descriptions className="gov-policy-result" size="small" bordered title="此次规则预览" column={1} items={[
      { key: "collect", label: "批量采集", children: `${profile.range} → ${sampleDecision}` },
      { key: "retention", label: "留存与处置", children: `${profile.retention} 天 · ${profile.deletion}` },
      { key: "logs", label: "日志 / 缓存 / 调试", children: <>{profile.logs}<br /><code>{'{ "event": "DEMO-POLICY-001", "payload": "不写入" }'}</code></> },
    ]} />
  </Space>;
}

function governanceTab(key: string, label: string, Icon: typeof ApartmentOutlined, description: string, content: React.ReactNode) {
  return {
    key, label, icon: <Icon aria-hidden="true" />,
    children: <div className="gov-tab-content">
      <header className="gov-section-intro">
        <h3>{label}</h3>
        <p>{description}</p>
      </header>
      {content}
    </div>,
  };
}

export function GovernanceSettings({ pageTheme = "light" }: { pageTheme?: "light" | "dark" }) {
  const scope = governanceAccount();
  const [tab, setTab] = useState("inventory");
  const [seed, setSeed] = useState<{ id: string; target: string; values: Values } | null>(null);
  const selectTab = (key: string) => { setTab(key); setSeed(null); };
  const register = (row: ComponentRow, target: "supply" | "scan" | "scope") => {
    if (target !== "scope") {
      selectTab(target);
      return;
    }
    const values: Values = { component: row.name, workspace: row.source, access: "待核查", risk: "待评估", data: row.data, componentId: row.key };
    setSeed({ id: `${row.key}:${Date.now()}`, target, values });
    setTab(target);
  };
  const recordProps = (id: string) => ({ id, scope, initial: seed?.target === id ? seed.values : undefined,
    seedKey: seed?.target === id ? seed.id : undefined, onSaved: () => setSeed(null) });
  const registeredScope = new Map(getLedgerRows(scope, "scope").filter((row) => row.values.componentId).reverse().map((row) => [row.values.componentId, row.values]));
  const items: TabsProps["items"] = [
    governanceTab("inventory", "组件清单", ApartmentOutlined, "按工作区查看组件来源、调用边界和风险登记。",
      <ComponentInventory onRegister={register} registeredScope={registeredScope} />),
    governanceTab("admission", "调用准入", SafetyCertificateOutlined, "查看运行策略和调用边界，按需校验 MCP 准入规则。",
      <ComponentAdmissionPanel onViewScope={() => selectTab("scope")} />),
    governanceTab("scope", "权限范围台账", LockOutlined, "登记组件的调用权限、可访问数据和风险依据。",
      <Ledger {...recordProps("scope")} fields={scopeFields} />),
    governanceTab("supply", "供应链变更", SwapOutlined, "401-3.3 · 查看模型、技能、MCP 和受管插件的实际变更。",
      <ComponentChangePanel key="supply" view="supply" />),
    governanceTab("flow", "数据流转", BranchesOutlined, "401-3.4 · 查看组件之间的数据类型、方向、处理方式及追溯入口。",
      <ComponentDataFlows />),
    governanceTab("scan", "扫描与处置", FileSearchOutlined, "401-3.5 · 执行当前部署检查，查看每项结果和建议处置。",
      <ComponentScanPanel />),
    governanceTab("sensitive", "敏感数据治理", DatabaseOutlined, "查看敏感数据分类、场景覆盖与授权边界，并运行可审计的合成样例自检。",
      <>
        <SensitiveDataGovernancePanel key={scope} />
        <Collapse items={[{ key: "preview", label: "采集、留存与删除规则示例（不生效 · 402-2.6）",
          children: <SensitivePolicy scope={scope} /> }]} />
      </>),
    governanceTab("local", "本地部署策略", DeploymentUnitOutlined, "402-3.3 · 配置受管本地推理的模型文件、缓存及接口访问。",
      <LocalAccessPanel />),
    governanceTab("config", "配置变更记录", SettingOutlined, "403.2 · 查看实际配置写入的主体、时间和变更摘要。",
      <ComponentChangePanel key="config" view="config" />),
  ];
  const dark = pageTheme === "dark";
  return <ConfigProvider theme={{
    algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      colorPrimary: dark ? "#79aaff" : "#2563eb",
      borderRadius: 8,
      ...(dark ? { colorBgContainer: "#141b2d", colorBgElevated: "#192337", colorBorderSecondary: "#263550" } : {}),
    },
    components: { Table: { cellPaddingBlockSM: 12, cellPaddingInlineSM: 14 } },
  }}>
    <section className="gov-workbench" aria-label="组件治理与策略">
      <header className="gov-masthead">
        <span className="gov-masthead-icon"><AuditOutlined aria-hidden="true" /></span>
        <div className="gov-masthead-copy">
          <span className="gov-eyebrow">安全治理</span>
          <h2>组件治理与策略</h2>
          <p>从组件发现到风险复核，集中查看准入策略与治理记录。</p>
        </div>
      </header>
      <div className="gov-compact-nav">
        <label htmlFor="gov-section-select">治理模块</label>
        <Select id="gov-section-select" value={tab} onChange={selectTab}
          options={items.map(({ key, label }) => ({ value: key, label }))} />
      </div>
      <Tabs className="gov-tabs" activeKey={tab} tabBarGutter={6} more={{ trigger: "click" }} animated={false}
        onChange={selectTab} destroyOnHidden items={items} />
    </section>
  </ConfigProvider>;
}
