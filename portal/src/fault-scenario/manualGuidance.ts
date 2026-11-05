export const MANUAL_FAULT_GUIDANCE_MARKER = "[CMDB 人工处置指南约束]";

export const MANUAL_FAULT_GUIDANCE_INSTRUCTIONS = [
  MANUAL_FAULT_GUIDANCE_MARKER,
  "核心要求：结合 CMDB 明确的实际部署环境给完整处置建议，不能只给组件内部操作。K3s/Kubernetes、裸 Docker、主机或托管环境使用对应访问路径，关联到平台不自动等于部署于该平台。",
  "完整人工步骤应包含：已有授权环境准备 → 目标/容器确认 → 组件访问 → 版本和实例核验 → 只读排查 → 条件性修复及审批 → 恢复验证；每步注明执行位置、前提和风险。",
  "当前只能用 CMDB 提供部署关系和字段；系统不得自行 SSH、kubectl exec 或登录数据库补证据，不索要/获取服务器和数据库密码、私钥、登录 token。已配置 MCP 的内部鉴权照常。",
  "参数有 CMDB 依据才绑定；未知 context、Namespace、Pod、容器、账号、端口由运维现场确认，不默认 root/default/mysql-0。密码只在运维本地交互输入，不提交给 AI。",
  "用户需要执行的运维命令和多行 shell/SQL 必须完整展示并可复制；不要只显示内部 skill 脚本调用，也不要为简短或详细模式删掉访问前置步骤。",
  "人工指南未执行，不能写已登录、已验证或已修复；它不生成自动执行 action。慢 SQL 不默认 KILL，只有具体证据、当前目标与审批满足后才给条件性处置。既有业务接口的权限和审批不扩大。",
].join("\n");

export function withManualFaultGuidance(
  content: string,
  meta?: Record<string, unknown> | null,
): string {
  if (content.includes(MANUAL_FAULT_GUIDANCE_MARKER)) return content;
  const boundAlarm = Boolean(meta?.alarmId || meta?.resId);
  const fault = /故障|告警|慢\s*sql|slow\s*sql|死锁|锁异常/iu.test(content);
  const analysis = /分析|根因|处置|建议|排查|处理|怎么|优化/iu.test(content);
  if (!boundAlarm && !(fault && analysis)) return content;
  return `${content}\n\n${MANUAL_FAULT_GUIDANCE_INSTRUCTIONS}`;
}
