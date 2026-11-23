import { useEffect, useRef, useState } from "react";
import { ArrowRightOutlined, EllipsisOutlined, ReloadOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { Alert, Button, Dropdown, Flex, Input, Modal, Radio, type MenuProps } from "antd";
import { useNavigate } from "react-router-dom";
import { boundaryConfirmation, deleteProtectionConfirmation, securityBoundariesApi,
  type BoundaryKey, type BoundarySnapshot, type BoundaryValue, type DeletePolicyCheck, type McpRemoteEndpoint, type ScanMode } from "../../api/securityBoundaries";

type Tone = "success" | "warning" | "danger" | "neutral";
type DeleteDraft = { previous: boolean; blocked: boolean; confirmation: string };
type BoundaryRow = { id: string; label: string; status: string; tone: Tone; detail: string; management: string };
const TIME = (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false });
const SOURCE = { environment: "部署环境变量覆盖", config_or_default: "运行配置或代码默认", fail_closed: "读取异常时默认禁止" };
const CONFIG_ENTRY = "安全边界总览";
const ROW_POLICIES: Record<string, BoundaryKey> = {
  tools: "tool_guard", mcp: "mcp_remote", skill: "skill_scan", domain: "domain_guard",
  output: "output_masking", isolation: "chat_isolation", text: "text_guard", documents: "controlled_documents",
  workspaceFiles: "controlled_workspace_files",
};
const POLICY_IMPACT: Record<BoundaryKey, string> = {
  tool_guard: "关闭后，工具风险守卫将不再判断调用；生产执行守卫和单独的调用准入规则不受此设置影响。",
  skill_scan: "仅作用于全局扫描模式；仅告警和关闭均不会阻断扫描发现的问题，工作区覆盖与例外仍按原策略执行。",
  domain_guard: "影响后续导入技能与 MCP 的业务领域检查，不改变运行时的端点或工具权限。",
  output_masking: "关闭后，受此规则覆盖的回复不再按出口规则打码。业务数据访问权限和其他脱敏规则不随之变更。",
  chat_isolation: "会话将按已验证身份隔离，旧共享会话不会自动迁移或重新分配。开启后不能在线关闭。",
  text_guard: "开启要求生产执行守卫和会话主体隔离均开启；受约束的入口将拒绝非文本内容及命中规则的输入。",
  controlled_documents: "开启要求生产执行守卫已开启；资料的授权、复核和审批仍按「受控资料」中的规则执行。",
  controlled_workspace_files: "禁止后，所有账号都不能通过对话新建文件。允许后，具备权限的发起人仍须逐次确认；已有禁用规则、脚本和其他生产限制不变。",
  mcp_remote: "只允许部署已信任主机上的精确远程端点。空列表拒绝全部远程端点；本配置不放行本地子进程，也不授予工具权限。",
};
type PolicyDraft = { key: BoundaryKey; label: string; previous: BoundaryValue | null; value: BoundaryValue | null; lines: string; confirmation: string };
const equalValue = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right);

function parseMcpLines(lines: string): McpRemoteEndpoint[] | undefined {
  const endpoints: McpRemoteEndpoint[] = [];
  for (const line of lines.split(/\r?\n/).map((entry) => entry.trim()).filter(Boolean)) {
    const match = /^(sse|streamable_http)\s+(\S+)$/.exec(line);
    if (!match || endpoints.length >= 64 || match[2].length > 1024) return undefined;
    endpoints.push({ transport: match[1] as McpRemoteEndpoint["transport"], url: match[2] });
  }
  return endpoints;
}
const SCAN = { block: "阻断模式", warn: "仅告警", off: "关闭" } as const;

function boundaryRows(data: BoundarySnapshot): BoundaryRow[] {
  const guards = data.mcp.production_guards;
  const isolation = data.chat_isolation_enabled;
  const mcpMode = data.mcp.endpoint_policy;
  const endpoints = data.mcp.declared_endpoint_count;
  const deletion = data.delete_protection;
  const workspaceFileMode = data.controls?.controlled_workspace_files?.value;
  return [
    { id: "delete", label: "全局删除保护", status: deletion.blocked ? "禁止彻底删除" : "未全局禁止删除",
      tone: deletion.blocked ? "success" : "warning", detail: "覆盖删除类管理请求及知识库彻底删除，不阻断知识库归档。未全局禁止不等于跳过权限或确认。",
      management: SOURCE[deletion.source] },
    { id: "execution", label: "生产执行守卫", status: guards ? "开启" : "关闭", tone: guards ? "success" : "danger",
      detail: "限制受管脚本、命令参数及敏感路径；受控操作执行前校验身份与审批。", management: "部署安全基线" },
    { id: "workspaceFiles", label: "对话新建工作区空文件",
      status: !guards ? "未启用生产执行守卫" : workspaceFileMode === true ? "禁止"
        : workspaceFileMode === false ? "允许 · 发起人确认" : "当前后端不支持",
      tone: guards && workspaceFileMode === true ? "success" : "neutral",
      detail: "在后台决定是否允许在当前工作区根目录新建空 .txt 或 .md；允许时才可在发起会话中确认执行。",
      management: CONFIG_ENTRY },
    { id: "tools", label: "工具风险守卫", status: data.tool_guard.enabled ? "开启" : "关闭", tone: data.tool_guard.enabled ? "success" : "warning",
      detail: `已加载 ${data.tool_guard.auto_deny_rule_count} 条自动拒绝规则。适用范围依工具及工作区配置，不代表所有工具均被覆盖。`, management: CONFIG_ENTRY },
    { id: "mcp", label: "MCP 服务与工具", status: !guards ? "端点守卫关闭" : mcpMode === "invalid" ? "配置无效 · 拒绝远程端点"
        : mcpMode === "exact" ? endpoints === 0 ? "精确白名单为空" : "精确白名单" : "主机规则",
      tone: !guards || mcpMode === "invalid" ? "danger" : mcpMode === "exact" ? "success" : "warning",
      detail: !guards ? "此处仅指生产端点守卫；各服务的工具授权仍需单独核对。" : mcpMode === "exact"
        ? `已声明 ${endpoints ?? "—"} 个精确端点。服务端点放行与工具授权是两道检查。` : mcpMode === "invalid"
          ? "无效名单不会回退到主机规则。" : `显式主机 ${data.mcp.declared_host_count} 个，另有内置范围；不按路径隔离。`, management: "远程端点准入" },
    { id: "calls", label: "工具与业务 API 调用", status: "按调用对象判定", tone: "neutral",
      detail: "可禁止已接入的 Agent 工具及智观 CMDB 精确查询，或恢复沿用原策略；不新增调用权限。", management: "组件治理与策略" },
    { id: "skill", label: "技能安全扫描", status: SCAN[data.global_skill_scan_mode], tone: data.global_skill_scan_mode === "block" ? "success" : "warning",
      detail: "当前全局扫描模式；工作区覆盖和例外名单单独核对。", management: CONFIG_ENTRY },
    { id: "domain", label: "导入领域限制", status: SCAN[data.domain_guard_mode], tone: data.domain_guard_mode === "block" ? "success" : "warning",
      detail: "按系统配置校验技能或工具的业务领域，不代表调用时的逐项授权。", management: CONFIG_ENTRY },
    { id: "output", label: "输出脱敏", status: data.output_masking_active ? "脱敏模式生效" : "未启用脱敏模式", tone: data.output_masking_active ? "success" : "warning",
      detail: "按配置对支持的输出执行规则匹配；不能证明所有敏感内容或所有渠道均已覆盖。", management: CONFIG_ENTRY },
    { id: "isolation", label: "对话会话隔离", status: isolation ? "开启" : "关闭", tone: isolation ? "success" : "warning",
      detail: "按登录主体约束适用的对话、历史和权限，不代表所有渠道均采用同一规则。", management: CONFIG_ENTRY },
    { id: "text", label: "对话文本输入检查", status: !data.text_guard_configured ? "未开启" : guards && isolation ? "已配置 · 依赖已满足" : "依赖未满足",
      tone: !data.text_guard_configured ? "neutral" : guards && isolation ? "success" : "danger",
      detail: "文本输入检查依赖安全防护与会话隔离，不覆盖多模态输入。", management: CONFIG_ENTRY },
    { id: "documents", label: "受控资料", status: !data.controlled_documents_configured ? "未开启" : guards ? "入口已配置" : "缺少生产守卫",
      tone: !data.controlled_documents_configured ? "neutral" : guards ? "success" : "danger",
      detail: "本页配置入口开关；紧急关停、批量上限和审批流程在「受控资料」管理。", management: "设置 → 受控资料（审批及限额）" },
    { id: "external", label: "网络隔离与上游数据权限", status: "需在环境中核验", tone: "neutral",
      detail: "入口、网络出口、容器隔离和上游数据授权不能从本页推断。端点自检也不能证明网络隔离。", management: "运维平台 / 上游系统" },
  ];
}

const errorMessage = (error: unknown, fallback: string) => error instanceof Error && !(error instanceof TypeError || error instanceof DOMException)
  ? error.message : fallback;

export function SecurityBoundaryOverview({ openProtection, openAdmission }: {
  openProtection: () => void;
  openAdmission?: () => void;
}) {
  const navigate = useNavigate();
  const [data, setData] = useState<BoundarySnapshot>();
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState<"check" | "configure" | "settings">();
  const [draft, setDraft] = useState<DeleteDraft>();
  const [policy, setPolicy] = useState<PolicyDraft>();
  const [savedPolicy, setSavedPolicy] = useState<{ key: BoundaryKey; label: string; value: BoundaryValue }>();
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [check, setCheck] = useState<DeletePolicyCheck>();
  const [saved, setSaved] = useState<boolean>();
  const action = useRef<AbortController>();

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setCheck(undefined);
    void securityBoundariesApi.snapshot(controller.signal).then((reply) => {
      if (!controller.signal.aborted) setData(reply);
    }).catch((issue: unknown) => {
      if (!controller.signal.aborted) {
        setData(undefined);
        setError(errorMessage(issue, "无法读取当前安全边界，请刷新重试。"));
      }
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [revision]);
  useEffect(() => () => action.current?.abort(), []);

  const deletion = data?.delete_protection;
  const canConfigure = deletion?.editable === true;
  const busy = loading || Boolean(running);
  const canSave = draft && canConfigure && draft.previous !== draft.blocked
    && (draft.blocked || draft.confirmation.trim() === deleteProtectionConfirmation(false));

  const policyValue = policy?.key === "mcp_remote" ? parseMcpLines(policy.lines) : policy?.value;
  const isWorkspaceFileMode = policy?.key === "controlled_workspace_files";
  const riskConfirmation = !isWorkspaceFileMode && (policy?.key === "chat_isolation" || policy?.key === "mcp_remote"
    || policy?.key === "controlled_documents" || policyValue === false || policyValue === "warn" || policyValue === "off");
  const canSavePolicy = policy && policyValue != null && !equalValue(policy.previous, policyValue)
    && (!riskConfirmation || policy.confirmation.trim() === boundaryConfirmation);

  async function run(kind: "check" | "configure" | "settings") {
    if (!data || busy || action.current || (kind === "configure" && !canSave) || (kind === "settings" && !canSavePolicy)) return;
    const controller = new AbortController();
    action.current = controller;
    setRunning(kind);
    setActionError("");
    setCheck(undefined);
    setSaved(undefined);
    setSavedPolicy(undefined);
    try {
      if (kind === "check") {
        const result = await securityBoundariesApi.verifyDeletion(controller.signal);
        if (!controller.signal.aborted) setCheck(result);
      } else if (kind === "settings" && policy && policyValue != null) {
        await securityBoundariesApi.configure(controller.signal, policy.key, policyValue, policy.previous,
          riskConfirmation ? policy.confirmation.trim() : boundaryConfirmation);
        if (!controller.signal.aborted) {
          setSavedPolicy({ key: policy.key, label: policy.label, value: policyValue });
          setPolicy(undefined);
          setRevision((value) => value + 1);
        }
      } else if (draft) {
        const reply = await securityBoundariesApi.configureDeletion(
          controller.signal, draft.blocked, draft.previous,
          draft.blocked ? deleteProtectionConfirmation(true) : draft.confirmation.trim(),
        );
        if (!controller.signal.aborted) {
          setData((current) => current && { ...current, delete_protection: reply.delete_protection });
          setSaved(reply.delete_protection.blocked);
          setDraft(undefined);
          setRevision((value) => value + 1);
        }
      }
    } catch (issue) {
      if (!controller.signal.aborted) {
        setActionError(errorMessage(issue, kind !== "check" ? "未能确认变更结果，请核对刷新后的状态，不要重复提交。" : "规则校验未完成。"));
        if (kind !== "check") {
          setDraft(undefined);
          setPolicy(undefined);
          setRevision((value) => value + 1);
        }
      }
    } finally {
      action.current = undefined;
      if (!controller.signal.aborted) setRunning(undefined);
    }
  }

  const rows = data ? boundaryRows(data) : [];
  const goToMcp = () => navigate("/mcp");

  type RowAction = { label: string; onClick: () => void; loading?: boolean };
  function controls(row: BoundaryRow): { main?: RowAction; secondary?: MenuProps["items"]; note?: string } {
    const admission = openAdmission ? { label: "前往调用准入", onClick: openAdmission } : undefined;
    const key = ROW_POLICIES[row.id];
    if (key) {
      const control = data?.controls?.[key];
      const secondary = row.id === "mcp" ? [
        { key: "mcp", label: "打开 MCP 管理", onClick: goToMcp },
        ...(admission ? [{ key: "admission", ...admission }] : []),
      ] : row.id === "output" ? [{ key: "protection", label: "查看防护概览", onClick: openProtection }] : undefined;
      if (key === "controlled_workspace_files" && control && !control.locked_reason && typeof control.value === "boolean") {
        const previous = control.value;
        return { main: {
          label: previous ? "允许新建（需确认）" : "禁止对话新建",
          onClick: () => setPolicy({ key, label: row.label, previous, value: !previous, lines: "", confirmation: "" }),
        }, note: "保存后对后续调用生效" };
      }
      if (key !== "controlled_workspace_files" && control && !control.locked_reason) return {
        main: { label: key === "mcp_remote" ? "配置远程端点" : "配置策略", onClick: () => setPolicy({
          key, label: row.label, previous: control.value, value: key === "chat_isolation" ? true : control.value,
          lines: Array.isArray(control.value) ? control.value.map((entry) => `${entry.transport} ${entry.url}`).join("\n") : "",
          confirmation: "",
        }) }, secondary,
      };
      return {
        main: row.id === "mcp" ? { label: "打开 MCP 管理", onClick: goToMcp }
          : row.id === "output" ? { label: "查看防护概览", onClick: openProtection } : undefined,
        note: control?.locked_reason ?? "当前后端未提供在线配置",
      };
    }
    switch (row.id) {
      case "delete": {
        const checkRule = () => void run("check");
        if (deletion && canConfigure) return {
          main: { label: "配置删除保护", onClick: () => setDraft({ previous: deletion.blocked, blocked: deletion.blocked, confirmation: "" }) },
          secondary: [{ key: "check", label: "校验删除规则", onClick: checkRule }],
          note: "保存后当前后端即时生效",
        };
        return {
          main: { label: "校验删除规则", onClick: checkRule, loading: running === "check" },
          note: deletion?.locked_reason ?? (deletion?.source === "environment"
            ? "由部署锁定" : "当前后端未提供在线配置"),
        };
      }
      case "execution":
        return { main: admission, note: "联动管理员鉴权和工具审批，由部署管理" };
      case "calls":
        return { main: admission };
      default:
        return {};
    }
  }

  return <section className="security-evidence-card security-boundaries-overview" aria-labelledby="security-boundary-title">
    <header className="security-evidence-heading boundary-heading">
      <span className="settings-tab-icon" aria-hidden="true"><SafetyCertificateOutlined /></span>
      <div className="security-evidence-heading-copy">
        <h4 id="security-boundary-title">系统安全边界</h4>
        <p>在此配置支持在线变更的规则，并核对实际生效状态。工具与业务 API 的逐项授权仍在「调用准入」管理。</p>
      </div>
      <div className="security-evidence-actions boundary-toolbar">
        <Button icon={<ReloadOutlined />} loading={loading} disabled={!!running}
          onClick={() => { setSaved(undefined); setSavedPolicy(undefined); setActionError(""); setRevision((value) => value + 1); }}>刷新状态</Button>
        {openAdmission && <Button type="primary" icon={<ArrowRightOutlined />} iconPlacement="end" onClick={openAdmission}>前往调用准入</Button>}
      </div>
    </header>
    {error && <Alert type="error" showIcon title={error} />}
    {actionError && <Alert type="error" showIcon title={actionError} />}
    {!loading && saved !== undefined && deletion?.blocked === saved && <Alert type="success" showIcon
      title={saved ? "已保存：全局删除保护已启用" : "已保存：全局删除保护已解除"}
      description={saved ? "当前后端会拦截受保护的删除请求。" : "当前后端不再全局拦截删除，业务权限及确认仍然有效。此操作未删除任何数据。"} />}
    {!loading && saved !== undefined && deletion && deletion.blocked !== saved && <Alert type="warning" showIcon
      title="保存后的状态与刷新结果不同，请核对当前后端及部署配置。" />}
    {!loading && savedPolicy && data && (equalValue(data.controls?.[savedPolicy.key]?.value, savedPolicy.value)
      ? <Alert type="success" showIcon title={`已保存并生效：${savedPolicy.label}`} />
      : <Alert type="warning" showIcon title={`${savedPolicy.label}的保存结果与刷新状态不同，请核对当前后端。`} />)}
    {check && <Alert showIcon type={check.decision === "blocked" ? "success" : "warning"}
      title={check.decision === "blocked" ? "知识库删除规则：拒绝彻底删除" : "知识库删除规则：未被全局保护拦截"}
      description={`${TIME(check.checked_at)} · 只评估实际规则，不读取资料、不执行删除，也不验证用户授权。`} />}
    <div className="security-evidence-table-group">
      <div className="security-evidence-table-head boundary-table-meta">
        <h5 id="security-boundary-table-title">边界清单 {data && <span>{rows.length} 项</span>}</h5>
        <span role="status">{loading ? "正在读取后端状态…" : data ? <>更新于 <time dateTime={data.queried_at}>{TIME(data.queried_at)}</time></> : "未读取到后端状态"}</span>
      </div>
      <div className="security-evidence-table-scroll" role="region" tabIndex={0} aria-labelledby="security-boundary-table-title" aria-busy={loading}>
        <table role="table" className="security-evidence-monitor-table boundary-table" aria-labelledby="security-boundary-table-title">
          <colgroup><col className="boundary-name-col" /><col className="boundary-status-col" /><col /><col className="boundary-actions-col" /></colgroup>
          <thead role="rowgroup"><tr role="row">
            <th role="columnheader" scope="col">安全边界</th>
            <th role="columnheader" scope="col">当前状态</th>
            <th role="columnheader" scope="col">生效范围与限制</th>
            <th role="columnheader" scope="col">管理位置与操作</th>
          </tr></thead>
          <tbody role="rowgroup">{rows.map((row) => {
            const { main, secondary, note } = controls(row);
            return <tr role="row" key={row.id}>
              <th role="rowheader" scope="row">{row.label}</th>
              <td role="cell"><span className={`security-evidence-badge ${row.tone}`}>{row.status}</span></td>
              <td role="cell" className="boundary-detail">{row.detail}</td>
              <td role="cell" className="boundary-management-cell"><div className="boundary-management">
                {main && <div className="boundary-row-actions">
                  <Button disabled={busy} loading={main.loading} onClick={main.onClick}>{main.label}</Button>
                  {secondary?.length ? <Dropdown menu={{ items: secondary }} trigger={["click"]} disabled={busy}>
                    <Button icon={<EllipsisOutlined />} aria-label={`${row.label}：更多操作`} title="更多操作" />
                  </Dropdown> : null}
                </div>}
                <span className="boundary-source">{row.management}{note && <> · {note}</>}</span>
              </div></td>
            </tr>;
          })}{!rows.length && <tr role="row"><td role="cell" colSpan={4} className="security-evidence-empty">{loading ? "正在读取边界清单…" : "暂无可显示的边界状态"}</td></tr>}</tbody>
        </table>
      </div>
      <p className="security-evidence-note">状态来自当前响应请求的后端，不代表其他副本、网络隔离或上游授权已经验证。</p>
    </div>
    <Modal title="配置全局删除保护" open={!!draft} onCancel={() => setDraft(undefined)} onOk={() => void run("configure")}
      okText={draft?.blocked === false ? "确认解除" : "确认启用"} cancelText="取消"
      confirmLoading={running === "configure"} closable={running !== "configure"}
      mask={{ closable: running !== "configure" }} keyboard={running !== "configure"}
      cancelButtonProps={{ disabled: running === "configure" }} okButtonProps={{ disabled: !canSave || busy, danger: draft?.blocked === false }}>
      {draft && <Flex vertical gap={12}>
        <div>当前状态：<strong>{draft.previous ? "保护开启（禁止彻底删除）" : "保护已解除"}</strong></div>
        <Radio.Group aria-label="保存后的保护状态" value={draft.blocked ? "blocked" : "released"} disabled={!!running}
          onChange={(event) => setDraft({ ...draft, blocked: event.target.value === "blocked", confirmation: "" })}>
          <Flex vertical gap={8}>
            <Radio value="blocked">启用保护（禁止彻底删除）</Radio>
            <Radio value="released">解除保护（仍须业务授权）</Radio>
          </Flex>
        </Radio.Group>
        <Alert showIcon type={draft.blocked ? "info" : "warning"}
          title={draft.blocked ? "受保护的删除请求将被拦截" : "这是系统级变更，不只影响知识库"}
          description={draft.blocked ? "知识库彻底删除及其他受保护的删除请求会被拒绝，知识库归档不受影响。"
            : "解除后，符合业务权限及确认要求的删除请求不再被此全局规则拦截。保存本身不会删除数据。"} />
        {!draft.blocked && draft.previous && <Flex vertical gap={6}>
          <label htmlFor="delete-protection-confirmation">输入「{deleteProtectionConfirmation(false)}」确认操作</label>
          <Input id="delete-protection-confirmation" value={draft.confirmation} autoComplete="off" disabled={!!running}
            onChange={(event) => setDraft({ ...draft, confirmation: event.target.value })} />
        </Flex>}
        <div>保存后当前后端即时生效，无需重启。</div>
      </Flex>}
    </Modal>
    <Modal title={policy ? `配置 · ${policy.label}` : "配置安全边界"} open={!!policy}
      onCancel={() => setPolicy(undefined)} onOk={() => void run("settings")} okText="确认保存" cancelText="取消"
      confirmLoading={running === "settings"} closable={running !== "settings"}
      mask={{ closable: running !== "settings" }} keyboard={running !== "settings"}
      cancelButtonProps={{ disabled: running === "settings" }} okButtonProps={{ disabled: !canSavePolicy || busy, danger: riskConfirmation }}>
      {policy && <Flex vertical gap={12}>
        <Alert showIcon type={riskConfirmation ? "warning" : "info"} title="生效范围与影响" description={POLICY_IMPACT[policy.key]} />
        {policy.key === "mcp_remote" ? <Flex vertical gap={6}>
          <div>当前模式：{policy.previous === null ? "按部署主机规则" : "精确端点名单"}</div>
          <label htmlFor="boundary-mcp-endpoints">每行填写传输类型和完整端点 URL（最多 64 行）</label>
          <Input.TextArea id="boundary-mcp-endpoints" disabled={busy} value={policy.lines} autoSize={{ minRows: 3, maxRows: 8 }}
            placeholder="streamable_http https://mcp.example.svc/api/mcp"
            status={!Array.isArray(policyValue) ? "error" : undefined}
            onChange={(event) => setPolicy({ ...policy, lines: event.target.value })} />
          {!Array.isArray(policyValue) && <span role="alert">请按「sse 或 streamable_http + 空格 + URL」逐行填写。</span>}
        </Flex> : policy.key === "chat_isolation" ? <div>保存后的状态：<strong>按已验证身份隔离</strong></div>
          : isWorkspaceFileMode ? <div>保存后的状态：<strong>{policyValue ? "禁止" : "允许 · 发起人确认"}</strong></div>
          : <Radio.Group aria-label="保存后的策略状态" disabled={busy}
            value={typeof policy.value === "boolean" ? String(policy.value) : policy.value}
            onChange={(event) => {
              const value = event.target.value as string;
              setPolicy({ ...policy, value: value === "true" ? true : value === "false" ? false : value as ScanMode, confirmation: "" });
            }}
            options={typeof policy.previous === "boolean" ? [{ value: "true", label: "开启" }, { value: "false", label: "关闭" }]
              : Object.entries(SCAN).map(([value, label]) => ({ value, label }))} />}
        {riskConfirmation && !equalValue(policyValue, policy.previous) && <Flex vertical gap={6}>
          <label htmlFor="boundary-setting-confirmation">输入「{boundaryConfirmation}」确认操作</label>
          <Input id="boundary-setting-confirmation" value={policy.confirmation} autoComplete="off" disabled={busy}
            onChange={(event) => setPolicy({ ...policy, confirmation: event.target.value })} />
        </Flex>}
        <div>保存后由当前后端按新策略处理后续请求，并记录变更人。</div>
      </Flex>}
    </Modal>
  </section>;
}
