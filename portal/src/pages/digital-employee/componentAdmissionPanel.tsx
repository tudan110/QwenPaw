import { useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Descriptions, Space, Table, Tag, Typography } from "antd";
import { Link } from "react-router-dom";
import { callAdmissionRows, type CallAdmissionRow } from "./callAdmissionFacts";
import { securityEvidenceApi, type AdmissionEvidence, type MCPAdmissionCheck } from "../../api/securityEvidence";

const decisions = { allow: "允许", deny: "拒绝" };
const caseNames = { registered: "精确白名单已登记端点", default_host: "主机模式 · 默认回环主机", unregistered: "未登记 · 保留测试地址" };
const policies = {
  read_scope: "内置能力 · 按既有授权使用",
  bounded_artifact: "受限产物写入",
  operator_read_classification: "运维配置的只读分类",
};

export function ComponentAdmissionPanel({ onViewScope }: { onViewScope: () => void }) {
  const [evidence, setEvidence] = useState<AdmissionEvidence>();
  const [probe, setProbe] = useState<MCPAdmissionCheck>();
  const [loadError, setLoadError] = useState("");
  const [probeError, setProbeError] = useState("");
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [revision, setRevision] = useState(0);
  const [showDetails, setShowDetails] = useState(false);
  const detailsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    setLoading(true);
    setEvidence(undefined);
    setProbe(undefined);
    setLoadError("");
    setProbeError("");
    void securityEvidenceApi.admission(signal).then((data) => {
      if (!signal.aborted) setEvidence(data);
    }, (error: Error) => {
      if (!signal.aborted) setLoadError(error.message);
    }).finally(() => {
      if (!signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [revision]);

  const runProbe = async () => {
    setChecking(true);
    setProbe(undefined);
    setProbeError("");
    try { setProbe(await securityEvidenceApi.checkMCPAdmission(true)); }
    catch (error) { setProbeError(error instanceof Error ? error.message : "无法完成策略检查"); }
    finally { setChecking(false); }
  };

  const mcp = evidence?.mcp;
  const rows = callAdmissionRows(evidence);
  const channels = [...new Set(rows.map((row) => row.channel))];
  const openDetails = () => {
    setShowDetails(true);
    detailsRef.current?.scrollIntoView({ block: "nearest" });
  };
  return <div className="gov-flow">
    <div className="gov-surface gov-toolbar gov-admission-status">
      <div className="gov-admission-meta">
        <Typography.Text strong>运行策略</Typography.Text>
        {mcp && <Tag variant="filled" color={mcp.production_guards ? "green" : "orange"}>生产守卫{mcp.production_guards ? "启用" : "关闭"}</Tag>}
        {!mcp && <Tag>{loading ? "正在读取运行配置" : "运行配置未核实"}</Tag>}
        {evidence && <span className="gov-secondary">读取时间：{new Date(evidence.queried_at).toLocaleString("zh-CN")}</span>}
      </div>
      <Button loading={loading} disabled={checking} onClick={() => setRevision((n) => n + 1)}>刷新策略</Button>
    </div>
    {loadError && <Alert type="error" showIcon title={loadError} />}
    {mcp && !mcp.production_guards && <Alert type="warning" showIcon
      title="生产守卫已关闭：下表中的生产守卫规则仅供参考，其他授权仍需单独核查。" />}
    <Card size="small" title="准入与权限边界" extra={<Button type="link" size="small" onClick={onViewScope}>查看权限范围台账</Button>}>
      <Typography.Paragraph type="secondary">
        生产守卫状态与 MCP 端点模式取自当前后端，其余内容说明规则及覆盖范围，不代表现场联通或业务授权已验证。
        “只读”与“需审批”是操作约束，不是风险等级；逐项定级以组件清单关联的台账记录为准。
      </Typography.Paragraph>
      <Table<CallAdmissionRow> className="gov-table gov-inner-table" size="small" rowKey="key" pagination={false} scroll={{ x: 880 }} dataSource={rows} columns={[
        { title: "调用对象", key: "target", width: 188,
          filters: channels.map((channel) => ({ text: channel, value: channel })),
          onFilter: (value, row) => row.channel === value,
          render: (_, row) => <Space orientation="vertical" size={2}>
            <Tag>{row.channel}</Tag><Typography.Text strong>{row.target}</Typography.Text>
          </Space> },
        { title: "准入规则", key: "rule", render: (_, row) => <>
          <Typography.Text strong>{row.mode}</Typography.Text><br />{row.detail}
          {row.link === "details" && evidence && <><br /><Button type="link" size="small" style={{ paddingInline: 0 }} onClick={openDetails}>查看工具和脚本明细</Button></>}
          {row.link === "mcp" && <><br /><Link to="/mcp">查看 MCP 管理</Link></>}
        </> },
        { title: "权限与数据边界", dataIndex: "boundary" },
        { title: "风险等级", dataIndex: "risk", width: 122,
          render: (risk: CallAdmissionRow["risk"]) => <Tag color={risk === "待评估" ? "gold" : "default"}>{risk}</Tag> },
      ]} />
    </Card>
    {evidence && <div ref={detailsRef}><Card size="small" title="工具和脚本策略明细" extra={<Button size="small" onClick={() => setShowDetails((v) => !v)}>{showDetails ? "收起" : "展开明细"}</Button>}>
      {showDetails && <Typography.Paragraph type="secondary">
        以下是运行配置中的分类与候选入口，不是当前工作区的已授权调用清单。
      </Typography.Paragraph>}
      {showDetails && <Descriptions bordered size="small" column={1} items={[
        ...Object.entries(policies).map(([key, label]) => ({ key, label, children: <Space size={[0, 4]} wrap>{evidence.tools.filter((tool) => tool.policy === key).map((tool) => <Tag key={tool.name}>{tool.name}</Tag>)}</Space> })),
        { key: "scripts", label: "脚本入口候选（调用时校验）", children: <Space size={[0, 4]} wrap>{evidence.script_candidates.map((name) => <Tag key={name}>{name}</Tag>)}</Space> },
      ]} />}
    </Card></div>}
    <Card size="small" title="MCP 准入自检" extra={<Button type="primary" size="small" loading={checking} disabled={loading || !mcp} onClick={() => void runProbe()}>验证当前准入规则</Button>}>
      <Typography.Paragraph type="secondary">校验准入规则，不发起连接。</Typography.Paragraph>
      {probeError && <Alert type="error" showIcon title={probeError} />}
      {probe && (probe.state === "ready" || probe.state === "host_policy") && <>
        <p>{new Date(probe.checked_at).toLocaleString("zh-CN")} · {probe.state === "host_policy" ? "主机模式" : "精确端点模式"}</p>
        <Table className="gov-table gov-inner-table" size="small" scroll={{ x: 520 }} pagination={false} rowKey="case" dataSource={probe.cases} columns={[
          { title: "检查对象", render: (_, row) => caseNames[row.case] },
          { title: "预期", render: (_, row) => decisions[row.expected] },
          { title: "实际策略判定", render: (_, row) => <Tag color={row.decision === "allow" ? "green" : "red"}>{decisions[row.decision]}</Tag> },
          { title: "核对结果", render: (_, row) => row.decision === row.expected ? <Tag color="green">符合预期</Tag> : <Tag color="volcano">与预期不符</Tag> },
        ]} />
      </>}
      {probe && probe.state !== "ready" && probe.state !== "host_policy" && <Alert showIcon type="warning" title={probe.state === "guards_disabled" ? "未执行：生产守卫已关闭" : probe.state === "invalid_policy" ? "未执行：精确白名单格式有误" : "未执行：没有精确白名单"} />}
    </Card>
    <Link to="/traces">查看实际执行：自监控 → 链路追踪 → 权限校验 / 异常核查</Link>
  </div>;
}
