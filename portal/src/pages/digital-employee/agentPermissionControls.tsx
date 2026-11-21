import { useEffect, useState } from "react";
import { Alert, Button, Card, Modal, Space, Switch, Table, Tag, Typography } from "antd";
import {
  listAgentConsent,
  listAgentPermissions,
  resolveAgentConsent,
  setAgentPermission,
  type AgentAccessBoundary,
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

const unavailable = {
  disabled: "工作区已关闭",
  inactive: "已配置启用 · 服务未就绪",
  error: "工作区配置异常",
};

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "请求失败";
}

interface ChatAccessScope {
  businessToolsEnabled: boolean;
  disabled: boolean;
  onToggle: () => void;
}

function AccessScopeOverview({ scope, boundary, loading, revoked }: {
  scope: ChatAccessScope; boundary?: AgentAccessBoundary; loading: boolean; revoked: number;
}) {
  const mcpPolicy = boundary?.mcp_policy;
  const mcpLabel = mcpPolicy === "exact" ? `MCP 精确白名单 · ${boundary?.mcp_endpoint_count ?? 0} 个端点`
    : mcpPolicy === "host" ? "MCP 主机规则"
    : mcpPolicy === "invalid" ? "MCP 白名单配置异常"
    : mcpPolicy === "off" ? "MCP 生产准入未启用" : null;
  const guards = boundary?.production_guards;
  return (
    <Card size="small" style={{ marginBottom: 16 }}>
      <Space orientation="vertical" size={12}>
        <div>
          <Space wrap>
            <Typography.Text strong>业务网络访问</Typography.Text>
            <Switch aria-label="业务联网" checked={scope.businessToolsEnabled} disabled={scope.disabled}
              checkedChildren="开" unCheckedChildren="关" onChange={scope.onToggle} />
            {mcpLabel && <Tag color={mcpPolicy === "invalid" || mcpPolicy === "off" ? "orange" : "blue"}>{mcpLabel}</Tag>}
          </Space><br />
          <Typography.Text type="secondary">关闭后，本页新消息仅调用已配置的模型；不会调用搜索、MCP、知识库或业务工具。</Typography.Text>
        </div>
        <div>
          <Space wrap>
            <Typography.Text strong>远程管理通道</Typography.Text>
            <Tag color={guards === true ? "green" : guards === false ? "orange" : undefined}>
              {guards === true ? "生产守卫已启用" : guards === false ? "生产守卫未启用" : loading ? "读取中" : "状态未核实"}
            </Tag>
          </Space><br />
          <Typography.Text type="secondary">生产守卫启用时，通用 Shell 不能直接执行 SSH、远程桌面客户端或集群管理命令。远程管理端口的可达性由部署侧策略控制。</Typography.Text>
        </div>
        <div>
          <Space wrap>
            <Typography.Text strong>内部资源</Typography.Text>
            {revoked > 0 && <Tag color="red">已撤销 {revoked} 项入口</Tag>}
          </Space><br />
          <Typography.Text type="secondary">可在下方撤销个人的 MCP 或 Skill 调用权限。智观数据查询仍沿用当前账号的数据权限。</Typography.Text>
        </div>
      </Space>
    </Card>
  );
}

export function AgentPermissionDialog({ agentId, agentName, onClose, accessScope }: {
  agentId: string; agentName: string; onClose: () => void; accessScope?: ChatAccessScope;
}) {
  const [items, setItems] = useState<AgentCapability[]>([]);
  const [boundary, setBoundary] = useState<AgentAccessBoundary>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [temporary, setTemporary] = useState<AgentCapability | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    listAgentPermissions(agentId, controller.signal).then((value) => {
      if (!controller.signal.aborted) {
        setItems(value.items);
        setBoundary(value.access_boundary);
      }
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
      const value = await listAgentPermissions(agentId);
      setItems(value.items);
      setBoundary(value.access_boundary);
      setTemporary(null);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open title={`${agentName} · ${accessScope ? "访问范围" : "智能体权限"}`} onCancel={onClose} footer={null} width={800}>
      {accessScope && <AccessScopeOverview scope={accessScope} boundary={boundary} loading={loading}
        revoked={items.filter((item) => item.configured && item.mode === "revoked").length} />}
      <p>此处设置个人授权。若 MCP 在工作区关闭或未就绪，需由管理员在 MCP 管理中处理；个人授权不能开启服务。启用后仍受工具审批和智观数据权限限制。</p>
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
          { title: "当前状态", render: (_, row) => row.configured ? <Space wrap><Tag color={row.mode === "revoked" ? "red" : row.mode === "ask" ? "gold" : "blue"}>{modeLabel[row.mode]}</Tag>{row.expires_at ? <span>截至 {new Date(row.expires_at * 1000).toLocaleTimeString()}</span> : null}</Space> : <Tag color={row.workspace_state === "error" ? "red" : row.workspace_state === "inactive" ? "orange" : undefined}>{row.workspace_state && row.workspace_state !== "active" ? unavailable[row.workspace_state] : "工作区暂不可用"}</Tag> },
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
