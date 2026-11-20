import { useState } from "react";
import { Alert, Button, Card, Col, Descriptions, Form, Input, Row, Select, Space, Tabs, Tag, Typography } from "antd";
import { ComponentInventory, type ComponentRow } from "./componentInventory";
import { field, Ledger, optional, getLedgerRows, governanceAccount, type RecordRow, type Values } from "./governanceLedger";
import { configFields, localAccessFields, scanFields, supplyFields, validateConfig, validateScan, validateSupply } from "./governanceForms";
import { previewSensitiveData, reviewExpired, syntheticData } from "./governanceFacts";
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
      setNotice("已保存预览设置。下方仅处理固定虚构样本。");
    } catch { setNotice("已更新本页预览，但浏览器存储不可用，无法保留设置。"); }
  };
  const example = previewSensitiveData(profile.mask);
  const sampleDecision = profile.range === "禁止批量敏感采集" ? "拒绝示例采集" : "示例采集等待人工审批";
  return <Space orientation="vertical" size="middle" className="gov-stack">
    <Alert type="warning" showIcon title="敏感数据规则预览 · 未应用到运行环境"
      description="可登记批量采集、留存、删除、日志、缓存及调试规则。此入口只在浏览器演算固定虚构样本；不会改动会话、真实数据或服务端日志。" />
    <Card size="small" title="登记策略">
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
    <Row gutter={[12, 12]}>
      <Col xs={24} lg={12}><Card size="small" title="预览前：虚构样本"><pre className="gov-preview">{JSON.stringify(syntheticData, null, 2)}</pre></Card></Col>
      <Col xs={24} lg={12}><Card size="small" title="预览后：脱敏结果"><pre className="gov-preview">{JSON.stringify(example, null, 2)}</pre></Card></Col>
    </Row>
    <Descriptions size="small" bordered title="此次规则预览" column={{ xs: 1, sm: 2, md: 2 }} items={[
      { key: "collect", label: "批量采集", children: `${profile.range} → ${sampleDecision}` },
      { key: "retention", label: "留存与处置", children: `${profile.retention} 天 · ${profile.deletion}` },
      { key: "logs", label: "日志 / 缓存 / 调试", children: <>{profile.logs}<br /><code>{'{ "event": "DEMO-POLICY-001", "payload": "不写入" }'}</code></> },
      { key: "mode", label: "下发状态", children: <Tag color="gold">只预览，未下发</Tag> },
    ]} />
  </Space>;
}

function scanBadge(row: RecordRow) {
  const { reviewBy, result, risk, disposition } = row.values;
  return <Space wrap size={4}>
    {reviewExpired(reviewBy) && <Tag color="red">复核已过期</Tag>}
    {result === "待扫描" && <Tag>待扫描</Tag>}
    {(risk === "高" || risk === "严重") && <Tag color="red">{risk}风险</Tag>}
    {disposition.startsWith("已") && <Tag color="blue">人工处置记录</Tag>}
    {!reviewBy && <Tag>未定复核期</Tag>}
  </Space>;
}

export function GovernanceSettings() {
  const scope = governanceAccount();
  const [tab, setTab] = useState("inventory");
  const [seed, setSeed] = useState<{ id: string; target: string; values: Values } | null>(null);
  const register = (row: ComponentRow, target: "supply" | "scan" | "scope") => {
    const version = row.version === "—" ? "" : row.version;
    const values: Values = target === "supply" ? { component: row.name, kind: row.kind, from: version,
      status: "待核验", origin: "待核对", scan: "待扫描", compatibility: "待检查", review: "待审核" }
      : target === "scan" ? { component: row.name, version: row.source === "Portal package.json" ? "" : version, result: "待扫描", disposition: "待评估", risk: "待分级" }
      : { component: row.name, workspace: row.source, access: "待核查", risk: "待评估", data: row.data, componentId: row.key };
    setSeed({ id: `${row.key}:${Date.now()}`, target, values });
    setTab(target);
  };
  const recordProps = (id: string) => ({ id, scope, initial: seed?.target === id ? seed.values : undefined,
    seedKey: seed?.target === id ? seed.id : undefined, onSaved: () => setSeed(null) });
  const registeredScope = new Map(getLedgerRows(scope, "scope").filter((row) => row.values.componentId).reverse().map((row) => [row.values.componentId, row.values]));
  return <section className="gov-page">
    <Typography.Title level={3}>组件治理与策略</Typography.Title>
    <Typography.Paragraph type="secondary">查看实际配置、登记核查和处置，或使用虚构样本预览规则。</Typography.Paragraph>
    <Tabs activeKey={tab} onChange={(key) => { setTab(key); setSeed(null); }} destroyOnHidden items={[
      { key: "inventory", label: "组件清单", children: <ComponentInventory onRegister={register} registeredScope={registeredScope} /> },
      { key: "scope", label: "权限范围台账", children: <Ledger {...recordProps("scope")} fields={scopeFields}
        description="登记组件权限、数据范围与风险。实际授权仍由原有工作区、个人权限和业务系统控制。" /> },
      { key: "supply", label: "供应链变更", children: <Ledger {...recordProps("supply")} fields={supplyFields} validate={validateSupply}
        description="登记新增、升级、替换和下线的来源核对、扫描、兼容检查、审批与回退。不会发布或下线组件。" /> },
      { key: "scan", label: "扫描与处置", children: <Ledger {...recordProps("scan")} fields={scanFields} validate={validateScan} adorn={scanBadge}
        description="记录外部扫描报告或待扫描任务，按复核日期标注到期。停用、隔离、下线和复测是处置登记，不会触发运行时动作。" /> },
      { key: "sensitive", label: "敏感数据", children: <SensitivePolicy scope={scope} /> },
      { key: "local", label: "本地部署策略", children: <Space orientation="vertical" className="gov-stack">
        <Alert type="info" showIcon title="81 验收范围：端侧部署不涉及" description="面向其他本地部署环境登记模型文件、缓存和本地接口的访问条件。站点若存在本地接口，请另行核对其监听范围、身份验证与文件权限。页面不读取主机路径，也不会下发系统权限。" />
        <Card size="small" title="本地部署访问模板（未验证、未下发）">
          <Descriptions size="small" bordered column={1} items={[
            { key: "model", label: "模型文件", children: "只向推理服务账号开放只读权限；模型更新由独立发布流程处理。" },
            { key: "cache", label: "推理缓存", children: "限制为本服务读写，按部署策略清理，避免共享目录与原始敏感数据落盘。" },
            { key: "api", label: "本地接口", children: "优先绑定回环或专用监听地址；需要跨服务访问时核验身份和调用范围。" },
          ]} />
        </Card>
        <Ledger {...recordProps("local")} fields={localAccessFields} description="本地资源访问模板与环境核查记录。" />
      </Space> },
      { key: "config", label: "配置变更记录", children: <Ledger {...recordProps("config")} fields={configFields} validate={validateConfig}
        description="记录提示词、安全规则、模型配置和工具编排的变更人、生效时间与回退。页面不自动采集系统变更，不写入运行配置。" /> },
    ]} />
  </section>;
}
