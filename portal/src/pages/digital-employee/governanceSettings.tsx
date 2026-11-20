import { useState } from "react";
import { Button, Card, Col, Descriptions, Form, Input, Row, Select, Space, Tabs, Tag, Typography } from "antd";
import { ComponentAdmissionPanel } from "./componentAdmissionPanel";
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
    <Row gutter={[12, 12]}>
      <Col xs={24} lg={12}><Card size="small" title="示例输入"><pre className="gov-preview">{JSON.stringify(syntheticData, null, 2)}</pre></Card></Col>
      <Col xs={24} lg={12}><Card size="small" title="脱敏预览"><pre className="gov-preview">{JSON.stringify(example, null, 2)}</pre></Card></Col>
    </Row>
    <Descriptions size="small" bordered title="此次规则预览" column={{ xs: 1, sm: 2, md: 2 }} items={[
      { key: "collect", label: "批量采集", children: `${profile.range} → ${sampleDecision}` },
      { key: "retention", label: "留存与处置", children: `${profile.retention} 天 · ${profile.deletion}` },
      { key: "logs", label: "日志 / 缓存 / 调试", children: <>{profile.logs}<br /><code>{'{ "event": "DEMO-POLICY-001", "payload": "不写入" }'}</code></> },
    ]} />
  </Space>;
}

function scanBadge(row: RecordRow) {
  const { reviewBy, result, risk } = row.values;
  return <Space wrap size={4}>
    {reviewExpired(reviewBy) && <Tag color="red">复核已过期</Tag>}
    {result === "待扫描" && <Tag>待扫描</Tag>}
    {(risk === "高" || risk === "严重") && <Tag color="red">{risk}风险</Tag>}
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
    <Tabs activeKey={tab} onChange={(key) => { setTab(key); setSeed(null); }} destroyOnHidden items={[
      { key: "inventory", label: "组件清单", children: <ComponentInventory onRegister={register} registeredScope={registeredScope} /> },
      { key: "admission", label: "调用准入", children: <ComponentAdmissionPanel /> },
      { key: "scope", label: "权限范围台账", children: <Ledger {...recordProps("scope")} fields={scopeFields} /> },
      { key: "supply", label: "供应链变更", children: <Ledger {...recordProps("supply")} fields={supplyFields} validate={validateSupply} /> },
      { key: "scan", label: "扫描与处置", children: <Ledger {...recordProps("scan")} fields={scanFields} validate={validateScan} adorn={scanBadge} actionLabel="登记扫描记录" /> },
      { key: "sensitive", label: "敏感数据", children: <SensitivePolicy scope={scope} /> },
      { key: "local", label: "本地部署策略", children: <Space orientation="vertical" className="gov-stack">
        <Card size="small" title="本地部署访问模板" extra={<Tag>81：端侧部署不涉及</Tag>}>
          <Descriptions size="small" bordered column={1} items={[
            { key: "model", label: "模型文件", children: "只向推理服务账号开放只读权限；模型更新由独立发布流程处理。" },
            { key: "cache", label: "推理缓存", children: "限制为本服务读写，按部署策略清理，避免共享目录与原始敏感数据落盘。" },
            { key: "api", label: "本地接口", children: "优先绑定回环或专用监听地址；需要跨服务访问时核验身份和调用范围。" },
          ]} />
        </Card>
        <Ledger {...recordProps("local")} fields={localAccessFields} />
      </Space> },
      { key: "config", label: "配置变更记录", children: <Ledger {...recordProps("config")} fields={configFields} validate={validateConfig} /> },
    ]} />
  </section>;
}
