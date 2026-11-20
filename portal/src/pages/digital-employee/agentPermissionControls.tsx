import { useEffect, useState } from "react";
import { Alert, Button, Modal, Space, Switch, Table, Tag } from "antd";
import {
  listAgentConsent,
  listAgentPermissions,
  resolveAgentConsent,
  setAgentPermission,
  type AgentCapability,
  type AgentConsent,
  type CapabilityChange,
} from "../../api/agentPermissions";

const modeLabel = {
  inherited: "按工作区配置允许",
  ask: "使用前需本人确认",
  revoked: "已撤销",
  temporary: "临时允许",
};

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "请求失败";
}

export function AgentPermissionDialog({ agentId, agentName, onClose }: {
  agentId: string; agentName: string; onClose: () => void;
}) {
  const [items, setItems] = useState<AgentCapability[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [temporary, setTemporary] = useState<AgentCapability | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    listAgentPermissions(agentId, controller.signal).then((value) => {
      if (!controller.signal.aborted) setItems(value.items);
    }).catch((err) => {
      if (!controller.signal.aborted) setError(errorText(err));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [agentId]);

  async function update(item: AgentCapability, mode: CapabilityChange) {
    setSaving(true);
    setError("");
    try {
      await setAgentPermission(agentId, item, mode);
      setItems((await listAgentPermissions(agentId)).items);
      setTemporary(null);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open title={`${agentName} · 智能体权限`} onCancel={onClose} footer={null} width={800}>
      <p>此处管理当前账号允许这个智能体使用的能力。开启后仍受工作区设置、工具审批和上游数据权限限制；撤销影响后续调用。</p>
      {error ? <Alert message={error} type="error" showIcon /> : null}
      {temporary ? (
        <Alert
          type="warning" showIcon
          message={`临时允许 ${temporary.name} 使用 15 分钟，到期后撤销。`}
          description={temporary.kind === "mcp" ? "范围：该服务中平台允许的工具调用；仍不能跳过生产守卫和后台审批。" : "范围：当前账号在此智能体的受管 Skill 调用。"}
          action={<Space><Button onClick={() => setTemporary(null)}>取消</Button><Button type="primary" loading={saving} onClick={() => void update(temporary, "temporary")}>允许</Button></Space>}
        />
      ) : null}
      <Table<AgentCapability>
        size="small" rowKey={(row) => `${row.kind}:${row.name}`} dataSource={items}
        loading={loading || saving} pagination={{ pageSize: 10, hideOnSinglePage: true }}
        locale={{ emptyText: "当前智能体未配置可展示的 Skill 或 MCP 服务" }}
        columns={[
          { title: "类型", dataIndex: "kind", render: (kind) => kind === "skill" ? "Skill" : "MCP 服务", filters: [{ text: "Skill", value: "skill" }, { text: "MCP 服务", value: "mcp" }], onFilter: (value, row) => row.kind === value },
          { title: "能力", dataIndex: "name" },
          { title: "当前状态", render: (_, row) => row.configured ? <Space wrap><Tag color={row.mode === "revoked" ? "red" : row.mode === "ask" ? "gold" : "blue"}>{modeLabel[row.mode]}</Tag>{row.expires_at ? <span>截至 {new Date(row.expires_at * 1000).toLocaleTimeString()}</span> : null}</Space> : <Tag>工作区未启用</Tag> },
          { title: "个人授权", render: (_, row) => <Space><Switch aria-label={`${row.name} 的个人权限`} checked={row.configured && row.mode !== "revoked"} disabled={!row.configured || saving} onChange={(checked) => void update(row, checked ? "default" : "revoked")} /><Button size="small" disabled={!row.configured || saving} onClick={() => setTemporary(row)}>临时允许</Button></Space> },
        ]}
      />
    </Modal>
  );
}

export function AgentConsentDialog({ agentId, sessionId, running, agentName }: {
  agentId: string; sessionId: string; running: boolean; agentName: string;
}) {
  const [request, setRequest] = useState<AgentConsent | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setRequest(null);
    setError("");
    if (!running || !sessionId) return;
    const controller = new AbortController();
    let timer: number | undefined;
    const refresh = async () => {
      try {
        const result = await listAgentConsent(agentId, sessionId, controller.signal);
        if (!controller.signal.aborted) setRequest(result.items[0] ?? null);
      } catch (err) {
        const status = (err as { status?: number })?.status;
        if (status === 401 || status === 404 || status === 503) return;
      }
      if (!controller.signal.aborted) timer = window.setTimeout(refresh, 1200);
    };
    void refresh();
    return () => { controller.abort(); if (timer !== undefined) window.clearTimeout(timer); };
  }, [agentId, sessionId, running]);

  async function answer(decision: "allow" | "deny") {
    if (!request || saving) return;
    setError("");
    setSaving(true);
    try {
      await resolveAgentConsent(agentId, sessionId, request.id, decision);
      setRequest((active) => active?.id === request.id ? null : active);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(false);
    }
  }

  if (!request || !running) return null;
  return (
    <Modal open title="智能体请求授权" closable={false} maskClosable={false} keyboard={false}
      footer={<Space><Button disabled={saving} onClick={() => void answer("deny")}>拒绝</Button><Button type="primary" loading={saving} onClick={() => void answer("allow")}>允许本次</Button></Space>}>
      <p><strong>{agentName}</strong> 为处理当前对话，申请向 MCP 服务发送这一次工具请求。</p>
      <dl><dt>服务</dt><dd>{request.service}</dd><dt>工具</dt><dd>{request.tool}</dd><dt>范围</dt><dd>仅此会话中当前等待的调用。查看后续请求时需要重新授权。</dd><dt>请在此时间前处理</dt><dd>{new Date(request.expires * 1000).toLocaleTimeString()}</dd></dl>
      {error ? <Alert message={error} type="error" showIcon /> : null}
    </Modal>
  );
}
