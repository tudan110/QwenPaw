import { useEffect, useId, useState, type ReactNode } from "react";
import { Alert, Button, InputNumber, Modal, Space } from "antd";
import { alarmExportApi, workOrderExportApi, type AlarmExportPreview, type BusinessExportSelection } from "../../api/alarmExport";

export function BusinessExportButton({ selection, children, className, disabled }: {
  selection: BusinessExportSelection;
  children: ReactNode;
  className?: string;
  disabled?: boolean;
}) {
  const [active, setActive] = useState<BusinessExportSelection | null>(null);
  const [preview, setPreview] = useState<AlarmExportPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const start = async () => {
    setActive(selection);
    setPreview(null);
    setError("");
    setBusy(true);
    try {
      const result = selection.source === "work_order"
        ? await workOrderExportApi.preview(selection.intent)
        : await alarmExportApi.preview(selection);
      setPreview(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "读取导出范围失败");
    } finally {
      setBusy(false);
    }
  };
  const download = async () => {
    if (!active || !preview?.ticket || busy) return;
    setBusy(true);
    try {
      const data = active.source === "work_order"
        ? await workOrderExportApi.download(active.intent, preview.ticket)
        : await alarmExportApi.download(active, preview.ticket);
      const file = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(file);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = active.source === "work_order" ? "work-orders.json"
        : active.source === "registry" ? "alarm-registry.json" : "alarms.json";
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setActive(null);
    } catch (cause) {
      setPreview(null);
      setError(cause instanceof Error ? cause.message : "导出失败，请重新预览。");
    } finally {
      setBusy(false);
    }
  };
  return <>
    <button type="button" className={className} disabled={disabled || busy} onClick={() => void start()}>{children}</button>
    <Modal title={active?.source === "work_order" ? "确认导出工单明细" : "确认导出告警明细"} open={!!active} okText="确认并下载" cancelText="关闭"
      onCancel={() => setActive(null)} onOk={download} confirmLoading={busy}
      closable={!busy} keyboard={!busy} maskClosable={!busy} cancelButtonProps={{ disabled: busy }}
      okButtonProps={{ disabled: !preview?.ticket || busy }}>
      {active?.source === "live" ? <>
        <p>查询时间：{active.begin_time} 至 {active.end_time}（告警平台时区）</p>
        <p>状态：{active.is_clear === "0" ? "未清除" : "已清除"}；级别：{active.severity || "全部"}
          {active.keyword ? `；关键词：${active.keyword}` : ""}
          {active.manage_ip ? `；管理 IP：${active.manage_ip}` : ""}
          {active.resource_type ? `；资源分类：${active.resource_type}` : ""}</p>
      </> : active?.source === "registry" ? <p>导出台账当前筛选范围，不限于当前页。
        {active.status ? ` 状态：${active.status}。` : ""}{active.search ? ` 搜索：${active.search}。` : ""}</p>
      : active?.source === "work_order" && preview?.scope ? <p>
        工单范围：{preview.scope.classify === 5 ? "已办工单" : "待办工单"}
        {preview.scope.startTime ? `；起始时间：${preview.scope.startTime}` : ""}
        {preview.scope.endTime ? `；结束时间：${preview.scope.endTime}` : ""}
      </p> : null}
      {busy && !preview ? <p role="status">正在核对导出数量…</p> : null}
      {preview && <Alert type={preview.ticket ? "info" : "warning"} showIcon message={preview.message} />}
      {preview?.ticket && <p>确认后将明细下载为本地 JSON 文件。请仅在授权范围内使用和保存。</p>}
      {error && <Alert type="error" showIcon message={error} />}
    </Modal>
  </>;
}

export function AlarmExportSettings({ className = "settings-section" }: { className?: string }) {
  const limitId = useId();
  const [limit, setLimit] = useState<number | null>(null);
  const [saved, setSaved] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void alarmExportApi.getPolicy(controller.signal).then(({ max_rows }) => {
      setLimit(max_rows);
      setSaved(max_rows);
    }, (cause) => {
      if (!controller.signal.aborted) setError(cause.message || "无法加载导出策略");
    });
    return () => controller.abort();
  }, []);
  const valid = typeof limit === "number" && Number.isInteger(limit) && limit >= 1 && limit <= 200;
  const save = async () => {
    if (!valid || limit === null) return;
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const result = await alarmExportApi.savePolicy(limit);
      setLimit(result.max_rows);
      setSaved(result.max_rows);
      setNotice(`已保存：单次最多导出 ${result.max_rows} 条。`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };
  return <section className={className}>
    <h4>业务明细导出管控</h4>
    <p>同一上限用于告警明细和已接入的待办、已办工单导出。未超限且通过权限与敏感数据校验时，可确认下载；超限直接拦截，不截断或自动拆单。普通查询和统计不受影响。</p>
    <Space wrap>
      <label htmlFor={limitId}>单次最多导出（条）</label>
      <InputNumber<number> id={limitId} min={1} max={200} step={1} value={limit} onChange={setLimit}
        disabled={saved === null || busy} />
      <Button type="primary" loading={busy} disabled={!valid || limit === saved || saved === null} onClick={save}>保存上限</Button>
    </Space>
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
