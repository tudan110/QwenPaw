import { useEffect, useState } from "react";
import { Alert, Button, Card, Descriptions, Space, Table, Tag, Typography } from "antd";
import { Link } from "react-router-dom";
import { securityEvidenceApi, type AdmissionEvidence, type MCPAdmissionCheck } from "../../api/securityEvidence";

const decisions = { allow: "允许", deny: "拒绝" };
const caseNames = { registered: "精确白名单已登记端点", default_host: "主机模式 · 默认回环主机", unregistered: "未登记 · 保留测试地址" };
const policies = {
  read_scope: "内置能力 · 按既有授权使用",
  bounded_artifact: "受限产物写入",
  operator_read_classification: "运维配置的只读分类",
};

export function ComponentAdmissionPanel() {
  const [evidence, setEvidence] = useState<AdmissionEvidence>();
  const [probe, setProbe] = useState<MCPAdmissionCheck>();
  const [loadError, setLoadError] = useState("");
  const [probeError, setProbeError] = useState("");
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [revision, setRevision] = useState(0);
  const [showDetails, setShowDetails] = useState(false);
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
  const mcpMode = mcp?.endpoint_policy === "invalid" ? "精确白名单格式有误"
    : mcp?.endpoint_policy === "exact" ? `精确端点白名单 · ${mcp.declared_endpoint_count ?? 0} 项`
    : mcp ? `主机规则 · ${mcp.declared_host_count} 个显式主机（另有内置范围）` : "—";
  return <Space orientation="vertical" size="middle" className="gov-stack">
    <Space wrap>
      <Typography.Text strong>工具、业务 API 与 MCP 调用准入</Typography.Text>
      {mcp && <Tag color={mcp.production_guards ? "green" : "orange"}>生产守卫{mcp.production_guards ? "启用" : "关闭"}</Tag>}
      <Button size="small" loading={loading} disabled={checking} onClick={() => setRevision((n) => n + 1)}>刷新策略</Button>
      {evidence && <Typography.Text type="secondary">读取时间：{new Date(evidence.queried_at).toLocaleString("zh-CN")}</Typography.Text>}
    </Space>
    <Alert type="info" showIcon title={mcp?.production_guards ? "后端有效配置与准入分层" : "准入规则说明"}
      description={mcp?.production_guards ? "按工作区、工具分类、当前账号和上游授权逐层检查。实际调用结果可在原会话的链路追踪中查看。" : "下方说明各通道的设计规则。只有读取到已启用的生产守卫配置，才能按当前生效规则取证。"} />
    {loadError && <Alert type="error" showIcon title={loadError} />}
    <Table size="small" bordered rowKey="channel" pagination={false} scroll={{ x: 770 }} columns={[
      { title: "调用通道", dataIndex: "channel", width: 145 },
      { title: "准入范围与权限", dataIndex: "policy" },
      { title: "操作影响与防护", dataIndex: "risk" },
    ]} dataSource={[
      { channel: "平台工具与 Skill", policy: "受管脚本在准入时核对路径、哈希和参数。工作区启用与个人授权仍生效。",
        risk: <><Tag color="blue">受限读取 / 生成产物</Tag><Tag color="volcano">受控操作需管理员审批</Tag><br />通用 shell、未获准脚本及禁止语法无法通过审批放开。</> },
      { channel: "业务 API · 智观 CMDB", policy: "以智观 CMDB 固定资产精确查询为例，使用当前登录账号的智观身份。",
        risk: <><Tag color="blue">只读查询</Tag>实际可见数据由智观控制；授权结果和工具结果分开记录。</> },
      { channel: "MCP 服务与工具", policy: <>{mcpMode}<br />{mcp && !mcp.endpoint_policy ? "此环境未配置精确白名单。" : "精确模式按传输、协议、主机、端口和路径匹配。"}</>,
        risk: <><Tag color="gold">按服务与工具规则</Tag>支持允许、审批或拒绝；实际规则看 <Link to="/mcp">MCP 管理</Link>。</> },
    ]} />
    <Card size="small" title="MCP 准入自检" extra={<Button type="primary" size="small" loading={checking} disabled={loading || !mcp} onClick={() => void runProbe()}>验证当前准入规则</Button>}>
      <Typography.Paragraph type="secondary">仅在后端判断规则，不连接目标或读取凭据。主机模式用默认回环主机作正向用例；它不代表已启用该 MCP 服务。</Typography.Paragraph>
      {probeError && <Alert type="error" showIcon title={probeError} />}
      {probe && (probe.state === "ready" || probe.state === "host_policy") && <>
        <p>{new Date(probe.checked_at).toLocaleString("zh-CN")} · {probe.state === "host_policy" ? "主机模式" : "精确端点模式"}</p>
        <Table size="small" pagination={false} rowKey="case" dataSource={probe.cases} columns={[
          { title: "检查对象", render: (_, row) => caseNames[row.case] },
          { title: "预期", render: (_, row) => decisions[row.expected] },
          { title: "实际策略判定", render: (_, row) => <Tag color={row.decision === row.expected ? "green" : "red"}>{decisions[row.decision]}</Tag> },
        ]} />
      </>}
      {probe && probe.state !== "ready" && probe.state !== "host_policy" && <Alert showIcon type="warning" title={probe.state === "guards_disabled" ? "未执行：生产守卫已关闭" : probe.state === "invalid_policy" ? "未执行：精确白名单格式有误" : "未执行：没有精确白名单"} />}
    </Card>
    {evidence && <Card size="small" title="工具和脚本策略明细" extra={<Button size="small" onClick={() => setShowDetails((v) => !v)}>{showDetails ? "收起" : "展开明细"}</Button>}>
      <Typography.Paragraph type="secondary">列出规则中已分类的工具和脚本入口候选。具体启用情况、版本和风险登记以「组件清单」为准。</Typography.Paragraph>
      {showDetails && <Descriptions bordered size="small" column={1} items={[
        ...Object.entries(policies).map(([key, label]) => ({ key, label, children: <Space size={[0, 4]} wrap>{evidence.tools.filter((tool) => tool.policy === key).map((tool) => <Tag key={tool.name}>{tool.name}</Tag>)}</Space> })),
        { key: "scripts", label: "待哈希及参数检查的脚本入口", children: <Space size={[0, 4]} wrap>{evidence.script_candidates.map((name) => <Tag key={name}>{name}</Tag>)}</Space> },
      ]} />}
    </Card>}
    <Link to="/traces">查看实际执行：自监控 → 链路追踪 → 权限校验 / 异常核查</Link>
  </Space>;
}
