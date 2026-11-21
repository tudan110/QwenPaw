import { useEffect, useRef, useState } from "react";
import { ArrowRightOutlined, EllipsisOutlined, ReloadOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { Alert, Button, Dropdown, Modal, type MenuProps } from "antd";
import { useNavigate } from "react-router-dom";
import { enableDeleteConfirmation, securityBoundariesApi, type BoundarySnapshot, type DeletePolicyCheck } from "../../api/securityBoundaries";

type Tone = "success" | "warning" | "danger" | "neutral";
type BoundaryRow = { id: string; label: string; status: string; tone: Tone; detail: string; management: string };
const TIME = (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false });
const SOURCE = { environment: "部署环境变量覆盖", config_or_default: "运行配置或代码默认", fail_closed: "读取异常时默认禁止" };
const CONFIG_ENTRY = "运维部署配置";
const SCAN = { block: "阻断模式", warn: "仅告警", off: "关闭" } as const;

function boundaryRows(data: BoundarySnapshot): BoundaryRow[] {
  const guards = data.mcp.production_guards;
  const isolation = data.chat_isolation_enabled;
  const mcpMode = data.mcp.endpoint_policy;
  const endpoints = data.mcp.declared_endpoint_count;
  const deletion = data.delete_protection;
  return [
    { id: "delete", label: "全局删除保护", status: deletion.blocked ? "禁止彻底删除" : "未全局禁止删除",
      tone: deletion.blocked ? "success" : "warning", detail: "覆盖删除类管理请求及知识库彻底删除，不阻断知识库归档。未全局禁止不等于跳过权限或确认。",
      management: SOURCE[deletion.source] },
    { id: "execution", label: "生产执行守卫", status: guards ? "开启" : "关闭", tone: guards ? "success" : "danger",
      detail: "限制受管脚本、命令参数及敏感路径；受控操作执行前校验身份与审批。", management: "守卫开关由部署管理" },
    { id: "tools", label: "工具风险守卫", status: data.tool_guard.enabled ? "开启" : "关闭", tone: data.tool_guard.enabled ? "success" : "warning",
      detail: `已加载 ${data.tool_guard.auto_deny_rule_count} 条自动拒绝规则。适用范围依工具及工作区配置，不代表所有工具均被覆盖。`, management: "管理后台 → 设置 → 安全" },
    { id: "mcp", label: "MCP 服务与工具", status: !guards ? "端点守卫关闭" : mcpMode === "invalid" ? "配置无效 · 拒绝远程端点"
        : mcpMode === "exact" ? endpoints === 0 ? "精确白名单为空" : "精确白名单" : "主机规则",
      tone: !guards || mcpMode === "invalid" ? "danger" : mcpMode === "exact" ? "success" : "warning",
      detail: !guards ? "此处仅指生产端点守卫；各服务的工具授权仍需单独核对。" : mcpMode === "exact"
        ? `已声明 ${endpoints ?? "—"} 个精确端点。服务端点放行与工具授权是两道检查。` : mcpMode === "invalid"
          ? "无效名单不会回退到主机规则。" : `显式主机 ${data.mcp.declared_host_count} 个，另有内置范围；不按路径隔离。`, management: "端点名单由部署管理" },
    { id: "calls", label: "工具与业务 API 调用", status: "按调用对象判定", tone: "neutral",
      detail: "可禁止已接入的 Agent 工具及智观 CMDB 精确查询，或恢复沿用原策略；不新增调用权限。", management: "组件治理与策略" },
    { id: "skill", label: "技能安全扫描", status: SCAN[data.global_skill_scan_mode], tone: data.global_skill_scan_mode === "block" ? "success" : "warning",
      detail: "当前全局扫描模式；工作区覆盖和例外名单单独核对。", management: "管理后台 → 设置 → 安全" },
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
      detail: "本页只核对入口开关与依赖；紧急关停、批量上限和审批流程在受控资料内核对。", management: "运维部署入口 · 设置 → 受控资料" },
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
  const [running, setRunning] = useState<"check" | "enable">();
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [check, setCheck] = useState<DeletePolicyCheck>();
  const [enabledNow, setEnabledNow] = useState(false);
  const action = useRef<AbortController>();

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setCheck(undefined);
    setActionError("");
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

  async function run(kind: "check" | "enable") {
    if (!data || running) return;
    const controller = new AbortController();
    action.current = controller;
    setRunning(kind);
    setActionError("");
    setCheck(undefined);
    setEnabledNow(false);
    try {
      if (kind === "check") {
        const result = await securityBoundariesApi.verifyDeletion(controller.signal);
        if (!controller.signal.aborted) setCheck(result);
      } else {
        const reply = await securityBoundariesApi.enableDeletion(controller.signal);
        if (!controller.signal.aborted) {
          setEnabledNow(reply.changed);
          setConfirm(false);
          setRevision((value) => value + 1);
        }
      }
    } catch (issue) {
      if (!controller.signal.aborted) {
        setActionError(errorMessage(issue, kind === "enable" ? "未能确认变更结果，请先刷新状态，不要重复提交。" : "规则校验未完成。"));
        if (kind === "enable") {
          setConfirm(false);
          setData(undefined);
        }
      }
    } finally {
      if (!controller.signal.aborted) setRunning(undefined);
    }
  }

  const deletion = data?.delete_protection;
  const canEnable = deletion && !deletion.blocked && deletion.source === "config_or_default";
  const busy = loading || Boolean(running);
  const rows = data ? boundaryRows(data) : [];
  const goToMcp = () => navigate("/mcp");

  type RowAction = { label: string; onClick: () => void; loading?: boolean };
  function controls(row: BoundaryRow): { main?: RowAction; secondary?: MenuProps["items"]; note?: string } {
    const admission = openAdmission ? { label: "前往调用准入", onClick: openAdmission } : undefined;
    switch (row.id) {
      case "delete":
        return {
          main: { label: "校验删除规则", onClick: () => void run("check"), loading: running === "check" },
          secondary: canEnable ? [{ key: "enable", label: "启用保护", onClick: () => setConfirm(true) }] : undefined,
          note: deletion?.source === "environment" ? "由部署锁定"
            : deletion?.blocked ? "不提供在线关闭" : canEnable ? "可启用" : "需由运维核对",
        };
      case "execution":
      case "calls":
        return { main: admission };
      case "mcp":
        return {
          main: admission ?? { label: "打开 MCP 管理", onClick: goToMcp },
          secondary: [
            ...(admission ? [{ key: "mcp", label: "打开 MCP 管理", onClick: goToMcp }] : []),
            { key: "protection", label: "查看防护概览", onClick: openProtection },
          ],
        };
      case "output":
        return { main: { label: "查看防护概览", onClick: openProtection } };
      default:
        return {};
    }
  }

  return <section className="security-evidence-card security-boundaries-overview" aria-labelledby="security-boundary-title">
    <header className="security-evidence-heading boundary-heading">
      <span className="settings-tab-icon" aria-hidden="true"><SafetyCertificateOutlined /></span>
      <div className="security-evidence-heading-copy">
        <h4 id="security-boundary-title">系统安全边界</h4>
        <p>查看当前防护状态、生效范围及管理位置。调用规则统一在「调用准入」配置。</p>
      </div>
      <div className="security-evidence-actions boundary-toolbar">
        <Button icon={<ReloadOutlined />} loading={loading} disabled={!!running}
          onClick={() => { setEnabledNow(false); setRevision((value) => value + 1); }}>刷新状态</Button>
        {openAdmission && <Button type="primary" icon={<ArrowRightOutlined />} iconPlacement="end" onClick={openAdmission}>前往调用准入</Button>}
      </div>
    </header>
    {error && <Alert type="error" showIcon title={error} />}
    {actionError && <Alert type="error" showIcon title={actionError} />}
    {enabledNow && deletion?.blocked && <Alert type="success" showIcon title="已保存，当前后端确认保护生效。" />}
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
                  <Button disabled={row.id === "delete" && busy} loading={main.loading} onClick={main.onClick}>{main.label}</Button>
                  {secondary?.length ? <Dropdown menu={{ items: secondary }} trigger={["click"]} disabled={row.id === "delete" && busy}>
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
    <Modal title={enableDeleteConfirmation} open={confirm} onCancel={() => setConfirm(false)} onOk={() => void run("enable")}
      okText="确认启用" cancelText="取消" confirmLoading={running === "enable"} closable={running !== "enable"}
      mask={{ closable: running !== "enable" }} keyboard={running !== "enable"} cancelButtonProps={{ disabled: running === "enable" }}>
      <p>这是系统级变更，不只影响知识库。启用后，知识库彻底删除以及受全局保护约束的其他资源删除都会被拒绝；知识库归档不受此开关阻断。</p>
      <p>变更保存到当前后端运行配置。本页只允许开启保护；解除保护或处理环境变量覆盖，须由运维办理。</p>
    </Modal>
  </section>;
}
