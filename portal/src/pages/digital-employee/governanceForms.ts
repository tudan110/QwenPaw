import { field, optional, type Field, type Values } from "./governanceLedger";

const changeActions = ["新增", "升级", "替换", "下线"];
const evidence = (label: string) => optional("evidence", label, "textarea");

export const supplyFields: Field[] = [
  field("component", "组件名称"), field("kind", "组件类型", ["模型", "技能", "工具", "插件", "连接器", "协议服务（MCP）", "第三方依赖", "外部服务"]),
  field("action", "变更类型", changeActions), field("status", "核验状态", ["待核验", "核验中", "退回整改", "已完成（人工记录）"]),
  optional("from", "原版本或来源"), optional("to", "目标版本或来源"),
  field("origin", "来源核对", ["待核对", "已核对（人工记录）", "来源有异常"]),
  field("scan", "漏洞扫描", ["待扫描", "已有结果（见依据）", "不适用（见依据）"]),
  field("compatibility", "兼容检查", ["待检查", "已有结果（见依据）", "不适用（见依据）"]),
  field("review", "审核进度", ["待审核", "已批准（人工记录）", "已拒绝（人工记录）"]),
  optional("effective", "计划生效时间", "datetime-local"), optional("owner", "负责岗位 / 工单处理人"),
  optional("rollback", "回退或下线计划", "textarea"), evidence("核验依据 / 工单编号"),
];

export const scanFields: Field[] = [
  field("component", "组件名称"), field("version", "版本或镜像标识"),
  field("result", "扫描报告结论", ["待扫描", "未发现（见报告）", "发现问题（见报告）", "扫描失败（见报告）"]),
  field("disposition", "处置登记", ["待评估", "待停用", "已停用（人工记录）", "已隔离（人工记录）", "已下线（人工记录）", "已复测（人工记录）"]),
  field("risk", "风险等级", ["待分级", "低", "中", "高", "严重"]), optional("scannedAt", "扫描时间", "datetime-local"),
  optional("reviewBy", "复核有效期", "date"), optional("found", "漏洞编号及受影响范围", "textarea"),
  optional("action", "处置措施 / 复测结论 / 恢复条件", "textarea"), evidence("报告来源 / 工单编号"),
];

export const configFields: Field[] = [
  field("subject", "变更对象"), field("kind", "变更分类", ["提示词", "安全规则", "模型配置", "工具编排"]),
  field("actor", "变更主体 / 岗位"), field("status", "生效与回退", ["待生效", "已生效（人工记录）", "待回退", "已回退（人工记录）"]),
  optional("effective", "实际或计划生效时间", "datetime-local"), optional("rollbackAt", "实际回退时间", "datetime-local"),
  { ...field("change", "变更前后摘要"), type: "textarea" }, optional("rollback", "回退方式及结果", "textarea"), evidence("配置差异、发布或工单编号"),
];

export const incidentFields: Field[] = [
  field("name", "事件 / 演练名称"), field("kind", "记录类型", ["告警处置", "安全事件", "风险测试计划", "应急演练计划"]),
  field("status", "当前阶段", ["待确认", "处理中", "已恢复（人工记录）", "已复盘（人工记录）", "待演练", "已演练（人工记录）"]),
  field("source", "来源与关联编号"), optional("owner", "负责岗位 / 处理人"),
  optional("alertAt", "发现 / 告警时间", "datetime-local"), optional("planAt", "计划演练时间", "datetime-local"),
  optional("handle", "处置时间及措施", "textarea"), optional("recoveredAt", "恢复时间", "datetime-local"),
  optional("recovery", "恢复验证", "textarea"), optional("review", "复盘结论与改进项", "textarea"), evidence("报告来源 / 工单编号"),
];

export const localAccessFields: Field[] = [
  field("name", "资源名称或用途"), field("kind", "资源类型", ["本地模型文件", "推理缓存", "本地接口"]),
  field("subject", "拟访问主体"), field("access", "登记权限", ["禁止访问", "只读", "服务账号专用", "需审批"]),
  field("binding", "适用环境", ["其他环境待核验", "本地部署模板", "81 端侧部署不涉及"]),
  optional("boundary", "路径类别或接口绑定范围（不填真实凭据）"), optional("auth", "拟认证方式 / 留存要求", "textarea"),
  evidence("核查依据 / 对应工单"),
];

export function validateSupply(values: Values) {
  if ((values.status.startsWith("已完成") || values.review.startsWith("已批准") ||
    values.origin.startsWith("已核对") || values.scan !== "待扫描" || values.compatibility !== "待检查") && !values.evidence) {
    return "登记已核验、审批或不适用结论时，请填写依据。";
  }
}

export function validateScan(values: Values) {
  if (values.result !== "待扫描" && (!values.evidence || !values.scannedAt)) return "登记扫描结果时，请填写扫描时间和报告来源。";
  if (values.result === "发现问题（见报告）" && !values.found) return "请填写报告中的漏洞编号或受影响范围。";
  if (values.disposition.startsWith("已") && (!values.action || !values.evidence)) return "登记已处置状态时，请填写处置措施及依据。";
}

export function validateConfig(values: Values) {
  if (values.status.startsWith("已") && (!values.effective || !values.evidence)) return "登记实际生效或回退时，请填写生效时间及依据。";
  if (values.status.startsWith("已回退") && (!values.rollbackAt || !values.rollback)) return "请填写实际回退时间及结果。";
}

export function validateIncident(values: Values) {
  if (values.status.startsWith("已恢复") && (!values.recoveredAt || !values.recovery)) return "请填写恢复时间和恢复验证。";
  if (values.status.startsWith("已复盘") && !values.review) return "请填写复盘结论和改进项。";
  if (values.status.startsWith("已演练") && (!values.review || !values.evidence)) return "登记已演练时，请填写结论及实际演练记录。";
}
