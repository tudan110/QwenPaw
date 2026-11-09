export const MANUAL_FAULT_GUIDANCE_MARKER = "[CMDB 人工处置指南约束]";

export const MANUAL_FAULT_GUIDANCE_INSTRUCTIONS = [
  MANUAL_FAULT_GUIDANCE_MARKER,
  "核心要求：结合 CMDB 明确的实际部署环境给完整处置建议，不能只给组件内部操作。K3s/Kubernetes、裸 Docker、主机或托管环境使用对应访问路径，关联到平台不自动等于部署于该平台。",
  "完整人工步骤应包含：已有授权环境准备 → 目标/容器确认 → 组件访问 → 版本和实例核验 → 只读排查 → 条件性修复及审批 → 恢复验证；每步注明执行位置、前提和风险。",
  "首轮回答的处置建议必须从 Step 0「进入管理环境」开始，环境表或总流程图不能代替操作步骤。若从服务器操作，先给运维人工 SSH 到已确认管理机的模板；已有授权 kubeconfig 的终端可直接操作。K3s 场景必须先核对 context、Namespace、Pod、容器，再给 kubectl exec -- mysql，不能直接从 mysql -h 开始；禁止 AI 执行 SSH 不等于禁止给用户人工命令。",
  "K8s 与 Docker 同时出现在关联列表时，先说明承载关系未唯一确认，并给条件性平台访问路径；不能用斜杠合并当成已确认部署，也不能因参数缺失省掉管理入口。部署宿主机不自动等于控制平面，数据库管理 IP 不自动等于 SSH 地址。",
  "CMDB db_port 可能是 NodePort/Service/宿主映射端口，不能直接用作容器内 MySQL 监听端口；容器内 DB_PORT 须有明确监听字段或运维现场核验。CMDB login_user 不作为指令账号，也不展示登录字段，DB_USER 由运维本地填写。宿主阈值告警和内存配置大小不能直接证明慢 SQL 根因或资源耗尽。",
  "当前只能用 CMDB 提供部署关系和字段；系统不得自行 SSH、kubectl exec 或登录数据库补证据，不索要/获取服务器和数据库密码、私钥、登录 token。已配置 MCP 的内部鉴权照常。",
  "参数有 CMDB 依据才绑定；未知 context、Namespace、Pod、容器、账号、端口由运维现场确认，不默认 root/default/mysql-0。密码只在运维本地交互输入，不提交给 AI。",
  "用户需要执行的运维命令和多行 shell/SQL 必须完整展示并可复制；不要只显示内部 skill 脚本调用，也不要为简短或详细模式删掉访问前置步骤。",
  "人工指南未执行，不能写已登录、已验证或已修复；它不生成自动执行 action。慢 SQL 不默认 KILL，只有具体证据、当前目标与审批满足后才给条件性处置。既有业务接口的权限和审批不扩大。",
].join("\n");

export function isManualFaultAdviceOnly(
  content: string,
  meta?: Record<string, unknown> | null,
): boolean {
  return !meta?.alarmId && !meta?.resId
    && /慢\s*sql|slow\s*sql/iu.test(content)
    && /如何|怎么|处置|建议|处理|排查|优化|方案/iu.test(content)
    && !/告警|工单/iu.test(content);
}

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
