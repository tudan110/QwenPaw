import { useEffect, useState } from "react";
import { Alert, Button, Card, Col, Row, Space, Statistic, Table, Tag, Typography } from "antd";
import { selfMonitorApi, type SelfMonitorAlert, type SelfMonitorAlertRule, type SelfMonitorTools } from "../../api/selfMonitor";
import { incidentFields, validateIncident } from "./governanceForms";
import { fmtDateTime, governanceAccount, Ledger } from "./governanceLedger";
import "./portalGovernance.css";

type Load<T> = { value?: T; error?: boolean };
type Rules = { enabled: boolean; evaluationIntervalS: number | null; items: SelfMonitorAlertRule[] };
type Alerts = { active: SelfMonitorAlert[]; recent: SelfMonitorAlert[] };
const showTs = (time: number | null) => time ? fmtDateTime(new Date(time * 1000).toISOString()) : "—";

export function IncidentRegister({ alert }: { alert: SelfMonitorAlert | null }) {
  const scope = governanceAccount();
  const nowLocal = (time: number) => new Date(time * 1000 - new Date(time * 1000).getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const initial = alert ? {
    name: alert.name, kind: "告警处置", status: "待确认", source: `自监控告警 #${alert.id} · ${alert.ruleId}`,
    alertAt: nowLocal(alert.startedAt), recoveredAt: alert.resolvedAt ? nowLocal(alert.resolvedAt) : "",
  } : undefined;
  return <section className="gov-page">
    <Typography.Title level={3}>安全事件与复盘</Typography.Title>
    <Typography.Paragraph type="secondary">记录告警、处置、恢复和复盘，或登记风险测试与演练计划。</Typography.Paragraph>
    <Ledger id="incidents" scope={scope} fields={incidentFields} validate={validateIncident} initial={initial}
      seedKey={alert ? String(alert.id) : undefined} />
  </section>;
}

export function RuntimeSecurityMonitor({ windowS, reloadNonce, onIncident, onTraces }: {
  windowS: number;
  reloadNonce: number;
  onIncident: (alert: SelfMonitorAlert) => void;
  onTraces: () => void;
}) {
  const [rules, setRules] = useState<Load<Rules>>({});
  const [tools, setTools] = useState<Load<SelfMonitorTools>>({});
  const [alerts, setAlerts] = useState<Load<Alerts>>({});
  const [showHistory, setShowHistory] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    const signal = controller.signal;
    setTools({});
    const fetchSource = <T,>(value: Promise<T>, set: (result: Load<T>) => void) => {
      void value.then((data) => { if (!signal.aborted) set({ value: data }); }, () => { if (!signal.aborted) set({ error: true }); });
    };
    const refresh = () => {
      fetchSource(selfMonitorApi.alertRules(signal), setRules);
      fetchSource(selfMonitorApi.alerts(50, signal), setAlerts);
      fetchSource(selfMonitorApi.tools(windowS, signal), setTools);
    };
    refresh();
    const timer = window.setInterval(refresh, 15000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [windowS, reloadNonce]);

  const totals = tools.value?.totals;
  const state = rules.value?.enabled === false ? "监控已停用" : rules.error ? "规则来源不可用" : rules.value ? "已读取后端规则" : "正在读取运行配置";
  const active = alerts.value?.active ?? [];
  const visibleAlerts = Array.from(new Map([...(showHistory ? alerts.value?.recent ?? [] : []), ...active]
    .map((row) => [row.id, row])).values()).sort((a, b) => Number(b.state === "firing") - Number(a.state === "firing") || b.startedAt - a.startedAt);
  return <section className="gov-page">
    <Space orientation="vertical" size="middle" className="gov-stack">
      <Typography.Title level={3}>运行安全监测</Typography.Title>
      {(rules.error || tools.error || alerts.error) && <Alert showIcon type="warning" title={`读取失败：${[rules.error && "规则", tools.error && "工具统计", alerts.error && "告警"].filter(Boolean).join("、")}`} />}
      <Row gutter={[12, 12]}>
        <Col xs={24} sm={12} xl={6}><Card size="small"><Statistic title="窗口工具调用" value={totals?.calls ?? "—"} /></Card></Col>
        <Col xs={24} sm={12} xl={6}><Card size="small"><Statistic title="工具异常（含拒绝 / 超时）" value={totals?.errors ?? "—"} /></Card></Col>
        <Col xs={24} sm={12} xl={6}><Card size="small"><Statistic title="触发中的运行告警" value={alerts.value && rules.value?.enabled ? active.length : "—"} /></Card></Col>
        <Col xs={24} sm={12} xl={6}><Card size="small"><Statistic title="规则引擎" value={state} valueStyle={{ fontSize: 19 }} /></Card></Col>
      </Row>
      <Card size="small" title="告警阈值" extra={rules.value?.evaluationIntervalS ? <Tag>每 {rules.value.evaluationIntervalS} 秒评估</Tag> : undefined}>
        <Table<SelfMonitorAlertRule> size="small" rowKey="id" dataSource={rules.value?.items ?? []} scroll={{ x: 800 }} pagination={{ pageSize: 6, hideOnSinglePage: true }}
          locale={{ emptyText: rules.error ? "无法读取规则" : rules.value?.enabled === false ? "自监控已停用" : rules.value ? "没有可展示的规则" : "正在读取规则" }} columns={[
            { title: "规则", dataIndex: "name" }, { title: "指标 / 标签", render: (_, row) => <>{row.metric || "规则计算指标"}{Object.keys(row.labels).length ? <><br /><small>{Object.entries(row.labels).map(([key, value]) => `${key}=${value}`).join("、")}</small></> : null}</> },
            { title: "阈值", render: (_, row) => row.threshold == null ? "使用配置的日预算" : `${row.op} ${row.threshold}` }, { title: "统计窗口 / 持续", render: (_, row) => `${row.kind === "counter_delta" ? `${row.windowS} 秒` : row.kind === "cost_daily" ? "自然日" : "当前采样"} / ${row.forS} 秒` },
            { title: "级别", render: (_, row) => <Tag color={row.severity === "critical" ? "red" : "orange"}>{row.severity === "critical" ? "严重" : "警告"}</Tag> },
          ]} />
      </Card>
      <Card size="small" title="运行告警" extra={<Button size="small" onClick={() => setShowHistory(!showHistory)}>{showHistory ? "仅显示触发中" : "显示近期历史"}</Button>}>
        <Table<SelfMonitorAlert> size="small" rowKey="id" dataSource={visibleAlerts} scroll={{ x: 950 }} pagination={{ pageSize: 7, hideOnSinglePage: true }}
          locale={{ emptyText: alerts.error ? "无法读取告警" : alerts.value ? "接口未返回告警记录" : "正在读取告警" }} columns={[
            { title: "告警 / 编号", render: (_, row) => <>{row.name}<br /><small>#{row.id} · {row.ruleId}</small></> },
            { title: "状态", render: (_, row) => <Tag color={row.state === "firing" ? "volcano" : "green"}>{row.state === "firing" ? "触发中" : "已恢复"}</Tag> },
            { title: "触发值 / 阈值", render: (_, row) => `${row.value} / ${row.threshold}` },
            { title: "触发时间", render: (_, row) => showTs(row.startedAt) }, { title: "恢复时间", render: (_, row) => showTs(row.resolvedAt) },
            { title: "处置", render: (_, row) => <Button type="link" size="small" onClick={() => onIncident(row)}>登记事件</Button> },
          ]} />
      </Card>
      <Card size="small" title="安全信号覆盖" extra={<Button type="link" onClick={onTraces}>前往链路异常核查</Button>}>
        <Table size="small" pagination={false} rowKey="signal" scroll={{ x: 710 }} dataSource={[
          { signal: "异常工具调用", source: "工具统计、工具调用事件", state: "窗口统计 + 逐次链路", action: "门限告警尚未接入" },
          { signal: "权限拒绝", source: "已接入的授权校验事件", state: "按会话查看原因和校验编号", action: "汇总及门限告警尚未接入" },
          { signal: "违规输出", source: "此页没有覆盖全部输出通道的事件源", state: "生产监测覆盖待核验", action: "门限告警尚未接入" },
          { signal: "核心运行故障", source: "自监控规则引擎", state: "按规则阈值触发和恢复", action: state },
        ]} columns={[
          { title: "指标 / 信号", dataIndex: "signal" }, { title: "来源", dataIndex: "source" }, { title: "当前覆盖", dataIndex: "state" }, { title: "告警状态", dataIndex: "action" },
        ]} />
      </Card>
    </Space>
  </section>;
}
