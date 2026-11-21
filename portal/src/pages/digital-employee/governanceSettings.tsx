import { useState } from "react";
import {
  ApartmentOutlined, AuditOutlined, BranchesOutlined, DatabaseOutlined, DeploymentUnitOutlined,
  FileSearchOutlined, LockOutlined, SafetyCertificateOutlined, SettingOutlined, SwapOutlined,
} from "@ant-design/icons";
import { ConfigProvider, Select, Tabs, theme, type TabsProps } from "antd";
import { SensitiveDataGovernancePanel } from "./sensitiveDataGovernancePanel";
import { ComponentAdmissionPanel } from "./componentAdmissionPanel";
import { ComponentInventory, type ComponentRow } from "./componentInventory";
import { field, Ledger, optional, getLedgerRows, governanceAccount, type Values } from "./governanceLedger";
import { ComponentChangePanel, ComponentDataFlows, ComponentScanPanel, LocalAccessPanel } from "./componentGovernancePanels";
import "./portalGovernance.css";

const scopeFields = [field("component", "组件名称"), field("workspace", "覆盖范围 / 工作区"),
  field("access", "登记调用权限", ["只读", "允许", "需人工确认", "拒绝", "按上游授权", "待核查"]),
  field("risk", "登记风险", ["待评估", "低", "中", "高", "严重"]), optional("data", "登记的数据访问范围", "textarea"),
  optional("reason", "评估依据及变更原因", "textarea"), { ...optional("componentId", "组件目录关联编号"), hidden: true }];

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

export function GovernanceSettings({ pageTheme = "light", initialTab = "inventory" }: {
  pageTheme?: "light" | "dark";
  initialTab?: "inventory" | "admission";
}) {
  const scope = governanceAccount();
  const [tab, setTab] = useState<string>(initialTab);
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
    governanceTab("supply", "供应链变更", SwapOutlined, "自动记录模型、技能、MCP 和受管插件的已保存变更，不代表审批或兼容性验证已通过。",
      <ComponentChangePanel key="supply" view="supply" />),
    governanceTab("flow", "数据流转", BranchesOutlined, "展示智观AI的数据流向、数据类型、处理方式及追溯入口。此表为部署链路说明，不是实时抓包。",
      <ComponentDataFlows />),
    governanceTab("scan", "扫描与处置", FileSearchOutlined, "检查技能、模型及 MCP 配置；启用 OSV 时检查已安装的 Python 依赖。未覆盖和未完成的项目会单独标明。",
      <ComponentScanPanel />),
    governanceTab("sensitive", "敏感数据治理", DatabaseOutlined, "管理敏感数据识别规则、适用场景与处理方式。",
      <SensitiveDataGovernancePanel key={scope} />),
    governanceTab("local", "本地部署策略", DeploymentUnitOutlined, "配置受管本地推理的模型文件、缓存及接口访问。",
      <LocalAccessPanel />),
    governanceTab("config", "配置变更记录", SettingOutlined, "自动记录已保存配置的变更主体、时间和摘要，不含敏感原文，也不代表配置已在运行时生效。",
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
