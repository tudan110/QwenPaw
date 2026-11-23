import type { AdmissionEvidence } from "../../api/securityEvidence";

export type AdmissionChannel = "工具 / Skill" | "业务 API" | "MCP";

export interface CallAdmissionRow {
  key: string;
  channel: AdmissionChannel;
  target: string;
  mode: string;
  detail: string;
  boundary: string;
  link?: "details" | "mcp";
}

export function remoteMcpRule(mcp?: AdmissionEvidence["mcp"]): Pick<CallAdmissionRow, "mode" | "detail"> {
  if (!mcp) return {
    mode: "当前状态未知",
    detail: "读取后端配置后，才能确认此环境使用精确白名单还是主机规则。",
  };
  const prefix = mcp.production_guards ? "" : "守卫关闭 · 配置为";
  if (mcp.endpoint_policy === "invalid") return {
    mode: `${prefix}精确白名单配置无效`,
    detail: mcp.production_guards ? "拒绝远程端点，不回退到主机规则。" : "若开启守卫，此配置将拒绝远程端点。",
  };
  if (mcp.endpoint_policy === "exact") {
    const count = mcp.declared_endpoint_count;
    return {
      mode: `${prefix}精确白名单${count === undefined ? "" : ` · ${count} 项`}`,
      detail: count === 0 ? (mcp.production_guards ? "名单为空，拒绝全部远程端点。" : "若开启守卫，空名单将拒绝全部远程端点。")
        : "按传输方式、协议、主机、端口和路径匹配；同主机的未登记路径也不匹配。",
    };
  }
  return {
    mode: `${prefix}主机规则 · ${mcp.declared_host_count} 个显式主机`,
    detail: "未配置精确白名单；主机规则还含回环及内置集群域名范围，不区分同主机的不同路径。",
  };
}

export function callAdmissionRows(evidence?: AdmissionEvidence): CallAdmissionRow[] {
  return [
    {
      key: "classified-tools", channel: "工具 / Skill", target: "已分类工具",
      mode: evidence ? `策略分类 · ${evidence.tools.length} 项` : "运行时工具分类",
      detail: "包含已知只读工具、受限产物工具和运维配置的只读分类；列入分类不代表在当前工作区启用。",
      boundary: "按工作区启用范围及适用的用户授权调用；受限产物不等于通用写入权限。",
      link: "details",
    },
    {
      key: "scripts", channel: "工具 / Skill", target: "受管脚本",
      mode: "固定脚本准入",
      detail: "执行前校验脚本路径、哈希和参数；通用 Shell、未获准脚本及禁止语法不能通过审批放开。",
      boundary: "仅允许通过校验的入口和操作；有权限的发起人须在原对话确认受控写入。候选入口不等于已启用或已通过校验。",
      link: "details",
    },
    {
      key: "unclassified-tools", channel: "工具 / Skill", target: "高危或未分类工具",
      mode: "普通用户拒绝",
      detail: "未分类不会自动放行，也不等于一律拒绝。",
      boundary: "当前仅具备后台执行权限的账号可发起；需复核身份并由发起人在对话内逐次确认，不能覆盖硬性拒绝规则。",
    },
    {
      key: "cmdb", channel: "业务 API", target: "智观 CMDB 资产精确查询",
      mode: "固定只读接口 · 已实现示例",
      detail: "仅按完整资产名称查询固定接口，不接受自选目标或任意查询条件。",
      boundary: "使用当前登录用户的智观凭据，资产可见范围由智观授权决定。此处不验证上游连通性。",
    },
    {
      key: "other-apis", channel: "业务 API", target: "其余 Agent 业务 API",
      mode: "统一白名单覆盖未确认",
      detail: "各调用入口的限制须分别核对；固定 CMDB 接口不能证明其他未登记 API 一律被拒绝。",
      boundary: "按各接口的调用身份、允许动作及数据范围核查。",
    },
    {
      key: "remote-mcp", channel: "MCP", target: "远程服务端点",
      ...remoteMcpRule(evidence?.mcp),
      boundary: "端点获准只表示符合连接规则，不代表已连通或已授予工具及数据访问权限。",
      link: "mcp",
    },
    {
      key: "stdio-mcp", channel: "MCP", target: "本地 stdio 服务",
      mode: "子进程命令白名单",
      detail: "守卫启用时，完整命令及参数须与登记项匹配；无登记项时不允许启动。",
      boundary: "该规则约束进程启动；不代表已授权调用服务中的工具。",
    },
    {
      key: "mcp-tools", channel: "MCP", target: "服务内工具",
      mode: "按服务与工具规则",
      detail: "支持允许、审批或拒绝；获准连接服务不等于获准调用其所有工具。",
      boundary: "按主体和工具核查实际配置；工具还受生产守卫及适用的用户授权约束，数据范围取决于上游。",
      link: "mcp",
    },
  ];
}
