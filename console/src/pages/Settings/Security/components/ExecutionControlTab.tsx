import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Card, Input, Space, Tag } from "antd";
import {
  executionControlApi,
  type ControlState,
  type ArchiveStatus,
} from "../../../../api/modules/executionControl";

export function ExecutionControlTab() {
  const [control, setControl] = useState<ControlState | null>(null);
  const [archive, setArchive] = useState<ArchiveStatus | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [state, audit] = await Promise.all([
        executionControlApi.get(),
        executionControlApi.archive(),
      ]);
      setControl(state);
      setArchive(audit);
      setError("");
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "无法读取执行控制状态",
      );
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const transition = async () => {
    if (!control || !reason.trim()) return;
    setBusy(true);
    try {
      const state = await executionControlApi.transition(
        !control.frozen,
        control.epoch,
        reason.trim(),
      );
      setControl(state);
      setReason("");
      setError("");
      await refresh();
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "操作失败，请刷新后重试",
      );
      // A timeout may occur after the server has persisted the freeze.
      // Fetch current state without silently repeating the action.
      setControl(await executionControlApi.get().catch(() => null));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="执行控制与审计归档">
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        {error && <Alert type="error" role="alert" message={error} />}
        <Alert
          type="info"
          showIcon
          message="冻结会阻断新执行并请求取消进行中的任务。远端操作可能已生效，仍需核验；解除冻结不会自动恢复旧任务。"
        />
        <div aria-live="polite">
          当前状态：
          <Tag color={control ? (control.frozen ? "red" : "green") : "default"}>
            {control ? (control.frozen ? "已冻结" : "允许执行") : "状态未知"}
          </Tag>
          {control && (
            <span>
              控制版本 {control.epoch}；最近说明：{control.reason || "无"}
            </span>
          )}
        </div>
        <label htmlFor="execution-control-reason">处置说明</label>
        <Input.TextArea
          id="execution-control-reason"
          value={reason}
          maxLength={500}
          onChange={(event) => setReason(event.target.value)}
        />
        <Space>
          <Button
            danger={!control?.frozen}
            type="primary"
            loading={busy}
            disabled={!control || !reason.trim()}
            onClick={() => void transition()}
          >
            {control?.frozen ? "解除冻结" : "冻结执行并请求停止"}
          </Button>
          <Button disabled={busy} onClick={() => void refresh()}>
            刷新状态
          </Button>
        </Space>
        {archive && (
          <p>
            待归档事件：{archive.pending}。独立存储的保留锁与权限需现场核验。
          </p>
        )}
      </Space>
    </Card>
  );
}
