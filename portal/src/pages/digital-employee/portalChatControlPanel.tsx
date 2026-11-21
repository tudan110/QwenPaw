import { useEffect, useState } from "react";
import { Button, Popconfirm, Space, Tag } from "antd";
import { getPortalChatControl, rollbackPortalChatBatch, setPortalChatPaused, type PortalChatControl } from "../../api/copawChat";

export function PortalChatControlPanel() {
  const [state, setState] = useState<PortalChatControl>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = async () => {
    setBusy(true);
    setError("");
    try {
      setState(await getPortalChatControl());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "读取关停状态失败");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { void refresh(); }, []);

  if (state?.enabled === false) return null;
  const last = state?.last_stop;
  const pending = last?.counts.accepted || 0;
  const rollback = last?.rollback;
  const canRollback = Boolean(state?.paused && last?.rollback_total && !pending
    && (!rollback || rollback.counts.failed));
  const update = async (action: () => Promise<PortalChatControl>) => {
    setError("");
    setBusy(true);
    try {
      setState(await action());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "更新失败，请刷新关停状态");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="settings-section" aria-labelledby="portal-chat-control-title">
      <div className="portal-model-block-head">
        <div>
          <h4 id="portal-chat-control-title">对话紧急关停</h4>
          <p>停止当前服务中所有正在运行的 Portal 对话，并暂停接收新对话请求。解除关停后，原页面可以手动继续已停止的文本回复。</p>
        </div>
        {state ? <Tag color={state.paused ? "red" : "green"}>{state.paused ? "已关停" : "可运行"}</Tag> : null}
      </div>
      <Space wrap>
        <Popconfirm
          title="确认关停所有正在运行的 Portal 对话？"
          description="解除关停后才允许发起新请求；已经完成的业务操作不会被撤销。"
          okText="确认关停"
          cancelText="取消"
          disabled={busy || !state || !!state.paused}
          onConfirm={() => update(() => setPortalChatPaused(true))}
        >
          <Button danger type="primary" disabled={busy || !state || !!state.paused}>一键关停对话</Button>
        </Popconfirm>
        {state?.paused ? (
          <Button onClick={() => update(() => setPortalChatPaused(false))} disabled={busy || pending > 0}>解除关停</Button>
        ) : null}
        <Popconfirm
          title="回滚最近一次关停批次？"
          description="仅撤回该批次纳入的本轮提问和回复，保留更早的历史。不会解除关停，也不会撤销已执行的业务操作。"
          okText="确认回滚"
          cancelText="取消"
          okButtonProps={{ danger: true }}
          disabled={busy || !canRollback}
          onConfirm={() => last && update(() => rollbackPortalChatBatch(last.id))}
        >
          <Button danger disabled={busy || !canRollback}>一键回滚</Button>
        </Popconfirm>
        <Button onClick={refresh} loading={busy}>刷新状态</Button>
      </Space>
      {error ? <p role="alert">{error}</p> : null}
      {last ? (
        <div role="status">
          <p>最近一次关停：{new Date(last.at * 1000).toLocaleString()}</p>
          {last.total === null ? <p>已登记关停，任务结果未能确认。请核对运行状态。</p> : (
            <p>纳入 {last.total} 个运行中对话 · 已停止 {last.counts.cancelled || 0}
              {` · 待确认 ${pending} · 已结束 ${last.counts.completed || 0}`}
              {` · 异常结束 ${(last.counts.failed || 0) + (last.counts.timeout || 0)} · 无法确认 ${last.counts.unknown || 0}`}
              {last.elapsed_ms !== null ? ` · 首次统计用时 ${last.elapsed_ms} ms` : ""}
            </p>
          )}
          {pending ? <p>仍有取消请求待确认。刷新状态后再回滚或解除关停。</p> : null}
          {rollback ? (
            <p>最近一次回滚：{new Date(rollback.at * 1000).toLocaleString()}
              {` · 已撤回 ${rollback.counts.recalled || 0} · 已跳过 ${rollback.counts.skipped || 0} · 失败 ${rollback.counts.failed || 0}`}
            </p>
          ) : null}
        </div>
      ) : null}
      {state?.timeout_seconds ? <p>单轮对话最多运行 {state.timeout_seconds} 秒，到时由服务端自动发出取消。</p> : null}
    </section>
  );
}
