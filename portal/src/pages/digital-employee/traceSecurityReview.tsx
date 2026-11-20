import { useState } from "react";
import { Button, Card, Col, Row, Segmented, Space, Table, Tag, Typography } from "antd";
import type { TraceSessionDetail } from "../../api/traces";
import { traceChecks, type TraceCheck } from "./governanceFacts";

export function TraceSecurityReview({ detail, onAuthorization }: {
  detail: TraceSessionDetail;
  onAuthorization: () => void;
}) {
  const [filter, setFilter] = useState("全部");
  const checks = traceChecks(detail.events);
  const authorization = checks.filter((item) => item.kind === "权限校验").length;
  const toolCalls = checks.filter((item) => item.kind === "工具调用").length;
  const agents = new Set(detail.events.map((item) => item.agent_id).filter(Boolean));
  const risks = checks.filter((item) => item.severity === "risk").length;
  const visible = checks.filter((item) => filter === "全部" || (filter === "仅异常" ? item.severity === "risk" : item.kind === filter));
  return <Space orientation="vertical" size="middle" className="gov-stack" style={{ padding: 16 }}>
    <Typography.Title level={4}>关键环节与异常核查</Typography.Title>
    <Row gutter={[12, 12]}>
      <Col xs={24} sm={12} xl={6}><Card size="small" title="智能体参与">记录到 {agents.size} 个主体<br /><Tag>未接入协同授权</Tag></Card></Col>
      <Col xs={24} sm={12} xl={6}><Card size="small" title="任务转派"><Tag>未接入逐跳转派</Tag><br />工具调用不代表任务委托</Card></Col>
      <Col xs={24} sm={12} xl={6}><Card size="small" title="权限与工具调用">{authorization} 条校验 · {toolCalls} 条调用<br /><Button type="link" size="small" onClick={onAuthorization}>查看校验依据</Button></Card></Col>
      <Col xs={24} sm={12} xl={6}><Card size="small" title="数据共享"><Tag>未接入共享审计</Tag><br />不能从返回结果推断数据转派</Card></Col>
    </Row>
    <Space wrap><Segmented options={["全部", "仅异常", "权限校验", "工具调用", "执行异常", "输出防护"]} value={filter} onChange={setFilter} /><Tag>已加载 {detail.events.length} / {detail.total} 条事件</Tag><Tag color="orange">异常或拒绝 {risks} 条</Tag></Space>
    <Table<TraceCheck> size="small" rowKey={(item) => `${item.ts}:${item.kind}:${item.target}:${item.reference}:${item.status}`}
      dataSource={visible} pagination={{ pageSize: 8, hideOnSinglePage: true }} scroll={{ x: 780 }}
      locale={{ emptyText: "当前筛选下没有已记录事件" }} columns={[
        { title: "时间", render: (_, row) => new Date(row.ts * 1000).toLocaleString("zh-CN") },
        { title: "环节", dataIndex: "kind" }, { title: "调用主体", dataIndex: "agent" },
        { title: "目标", dataIndex: "target" },
        { title: "记录结果", render: (_, row) => <Tag color={row.severity === "risk" ? "orange" : row.severity === "notice" ? "blue" : "green"}>{row.status}</Tag> },
        { title: "校验 / 调用编号", render: (_, row) => row.reference || "—" },
      ]} />
  </Space>;
}
