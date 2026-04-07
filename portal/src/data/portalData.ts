import type {
  DigitalEmployee,
  PortalAgent,
  PortalStatSummary,
} from "../types/portal";

export const portalStats: PortalStatSummary = {
  total: 6,
  active: 5,
  tasksToday: 156,
  efficiency: 92,
};

export const agentTypeNames = {
  alert: "告警处理",
  fault: "故障自愈",
  inspection: "巡检执行",
  capacity: "容量优化",
  security: "安全分析",
  change: "变更执行",
};

export const portalAgents: PortalAgent[] = [
  {
    id: "AG001",
    name: "故障速应",
    type: "alert",
    status: "active",
    color: "#409eff",
    icon: "fa-solid fa-bell",
    description: "故障检测与自动修复",
    skills: ["告警分析", "智能分类", "流程触发", "通知推送"],
    execCount: 1256,
    successRate: 96.5,
    avgDuration: "2.3s",
    lastRunTime: "2026-03-20 18:00:00",
    employeeId: "fault",
  },
  {
    id: "AG002",
    name: "资产管家",
    type: "fault",
    status: "active",
    color: "#e6a23c",
    icon: "fa-solid fa-rotate-right",
    description: "快速发现与智能纳管",
    skills: ["故障检测", "根因分析", "自愈执行", "验证恢复"],
    execCount: 328,
    successRate: 89.5,
    avgDuration: "45s",
    lastRunTime: "2026-03-20 18:00:00",
    employeeId: "resource",
  },
  {
    id: "AG003",
    name: "巡弋小卫",
    type: "inspection",
    status: "active",
    color: "#67c23a",
    icon: "fa-solid fa-clipboard-check",
    description: "自动化巡检与报告",
    skills: ["巡检执行", "数据采集", "报告生成", "异常上报"],
    execCount: 89,
    successRate: 100,
    avgDuration: "5m",
    lastRunTime: "2026-03-20 18:00:00",
    employeeId: "inspection",
  },
  {
    id: "AG004",
    name: "数据洞察员",
    type: "capacity",
    status: "active",
    color: "#9c27b0",
    icon: "fa-solid fa-chart-pie",
    description: "数据分析与报表生成",
    skills: ["容量分析", "趋势预测", "优化建议", "弹性伸缩"],
    execCount: 56,
    successRate: 95.2,
    avgDuration: "3m",
    lastRunTime: "2026-03-20 18:00:00",
    employeeId: "query",
  },
  {
    id: "AG005",
    name: "知库小典",
    type: "security",
    status: "active",
    color: "#f56c6c",
    icon: "fa-solid fa-shield-halved",
    description: "运维知识问答",
    skills: ["威胁检测", "行为分析", "风险评估", "自动阻断"],
    execCount: 2341,
    successRate: 98.8,
    avgDuration: "1.5s",
    lastRunTime: "2026-03-20 18:00:00",
    employeeId: "knowledge",
  },
  {
    id: "AG006",
    name: "工单管家",
    type: "change",
    status: "stopped",
    color: "#909399",
    icon: "fa-solid fa-pen-to-square",
    description: "工单处理与流程自动化",
    skills: ["变更审批", "任务执行", "过程监控", "结果验证"],
    execCount: 45,
    successRate: 97.8,
    avgDuration: "8m",
    lastRunTime: "2026-03-20 18:00:00",
    employeeId: "order",
  },
];

export const digitalEmployees: DigitalEmployee[] = [
  {
    id: "resource",
    name: "资产管家",
    desc: "快速发现与智能纳管",
    icon: "fa-server",
    tasks: 1256,
    success: "99.2%",
    status: "running",
    urgent: false,
    gradient: "linear-gradient(135deg, #3B82F6, #1D4ED8)",
    capabilities: ["IP扫描发现", "云账号导入", "API自动发现", "协议适配", "资源建模", "拓扑生成"],
    quickCommands: [
      "扫描10.0.1.0/24网段的网络设备",
      "导入阿里云账号发现资源",
      "发现PaaS组件（Kafka/Redis/MySQL）",
      "自动纳管新上线的服务器",
    ],
    welcome:
      "您好！我是资产管家。快速发现与智能纳管。<br><br>我可以帮您完成以下工作：<br>• IP扫描发现 - 自动扫描指定网段，快速发现网络设备<br>• 云账号导入 - 一键导入阿里云、AWS、华为云等账号<br>• API自动发现 - 通过API接口自动发现各类资源<br>• 协议适配 - 支持SNMP、SSH、Restful等多种协议<br>• 资源建模 - 自动构建CMDB资源模型<br>• 拓扑生成 - 自动生成资源关联拓扑图<br><br>请直接输入您的需求，或选择下方的快捷命令。",
  },
  {
    id: "fault",
    name: "故障速应",
    desc: "故障检测与自动修复",
    icon: "fa-wrench",
    tasks: 892,
    success: "97.8%",
    status: "running",
    urgent: true,
    gradient: "linear-gradient(135deg, #EF4444, #DC2626)",
    capabilities: ["故障诊断", "根因定位", "自动修复", "故障恢复", "0-1-5-10响应"],
    quickCommands: ["服务器10.0.1.25连接不上", "数据库响应很慢", "网站无法访问", "网络丢包严重"],
    welcome:
      "您好！我是故障速应。故障检测与自动修复。<br><br>我可以帮您完成以下工作：<br>• 故障诊断 - 秒级发现故障，智能分析故障类型<br>• 根因定位 - 结合拓扑、日志快速定位故障根源<br>• 自动修复 - 低风险操作自动执行，高风险等待授权<br>• 故障恢复 - 自动执行恢复策略，验证业务可用性<br>• 0-1-5-10响应 - 0秒发现、1分钟定位、5分钟修复、10分钟恢复<br><br>请直接输入您的故障描述，或选择下方的快捷命令。",
  },
  {
    id: "inspection",
    name: "巡弋小卫",
    desc: "自动化巡检与报告",
    icon: "fa-clipboard-check",
    tasks: 3421,
    success: "100%",
    status: "stopped",
    urgent: false,
    gradient: "linear-gradient(135deg, #10B981, #059669)",
    capabilities: ["系统巡检", "安全巡检", "健康检查", "报告生成", "异常闭环"],
    quickCommands: ["执行全面系统巡检", "生成本周运维报告", "检查磁盘使用率", "巡检核心网络设备"],
    welcome:
      "您好！我是巡弋小卫。自动化巡检与报告生成。<br><br>我可以帮您完成以下工作：<br>• 系统巡检 - 对服务器、数据库、中间件执行自动化检查<br>• 安全巡检 - 检查安全配置、漏洞、异常登录<br>• 健康检查 - 评估系统资源、性能、可用性<br>• 报告生成 - 自动生成巡检报告和健康评分<br>• 异常闭环 - 巡检异常自动生成处置工单<br><br>请直接输入您的巡检需求，或选择下方的快捷命令。",
  },
  {
    id: "order",
    name: "工单管家",
    desc: "工单处理与流程自动化",
    icon: "fa-ticket-alt",
    tasks: 5678,
    success: "98.5%",
    status: "running",
    urgent: false,
    gradient: "linear-gradient(135deg, #F59E0B, #D97706)",
    capabilities: ["工单创建", "智能分派", "处理跟踪", "自动关闭", "统计报表"],
    quickCommands: ["创建紧急变更工单", "查看待处理工单", "批量处理工单", "导出工单统计"],
    welcome:
      "您好！我是工单管家。工单处理与流程自动化。<br><br>我可以帮您完成以下工作：<br>• 工单创建 - 智能解析需求，自动创建标准化工单<br>• 智能分派 - 基于技能、负载自动分派最优处理人<br>• 处理跟踪 - 全流程可视化，实时跟踪处理进度<br>• 自动关闭 - 完成后自动验证并归档<br>• 统计报表 - 自动生成工单处理统计和分析报告<br><br>请直接输入您的工单需求，或选择下方的快捷命令。",
  },
  {
    id: "query",
    name: "数据洞察员",
    desc: "数据分析与报表生成",
    icon: "fa-chart-bar",
    tasks: 2134,
    success: "99.6%",
    status: "running",
    urgent: false,
    gradient: "linear-gradient(135deg, #8B5CF6, #7C3AED)",
    capabilities: ["指标查询", "报表生成", "趋势分析", "数据可视化", "自定义取数"],
    quickCommands: ["查询CPU使用率TOP10", "生成业务可用性报表", "分析告警趋势", "导出性能数据"],
    welcome:
      "您好！我是数据洞察员。数据分析与报表生成。<br><br>我可以帮您完成以下工作：<br>• 指标查询 - 自然语言查询各类监控指标<br>• 报表生成 - 自动生成日报、周报、月报<br>• 趋势分析 - 分析指标趋势，预测容量需求<br>• 数据可视化 - 生成直观的图表和仪表盘<br>• 自定义取数 - 按需提取数据，支持多种格式导出<br><br>请直接输入您的数据需求，或选择下方的快捷命令。",
  },
  {
    id: "knowledge",
    name: "知库小典",
    desc: "运维知识问答",
    icon: "fa-book-open",
    tasks: 4521,
    success: "99.1%",
    status: "running",
    urgent: false,
    gradient: "linear-gradient(135deg, #06B6D4, #0891B2)",
    capabilities: ["知识问答", "方案推荐", "故障案例", "最佳实践", "智能培训"],
    quickCommands: ["如何处理Oracle死锁", "Nginx性能优化建议", "Redis缓存穿透解决方案", "查看故障复盘"],
    welcome:
      "您好！我是知库小典。运维知识问答。<br><br>我可以帮您完成以下工作：<br>• 知识问答 - 回答各类运维技术问题<br>• 方案推荐 - 基于历史案例推荐最佳处置方案<br>• 故障案例 - 检索相似故障的处理经验<br>• 最佳实践 - 提供各技术栈的最佳实践建议<br>• 智能培训 - 为新员工提供运维知识培训<br><br>请直接输入您的问题，或选择下方的快捷命令。",
  },
];

export const employeeStepDescriptions = {
  resource: ["正在扫描指定IP段...", "识别设备类型和厂商...", "探测开放端口和服务...", "构建资源模型关系..."],
  fault: ["采集告警指标数据...", "关联拓扑关系分析...", "定位故障根因...", "执行自动修复..."],
  inspection: ["生成巡检计划...", "执行巡检项检查...", "计算健康评分...", "生成巡检报告..."],
  order: ["解析工单内容...", "智能分类分级...", "自动分派处理...", "跟踪处理进度..."],
  query: ["解析查询意图...", "生成SQL语句...", "执行数据提取...", "生成可视化..."],
  knowledge: ["理解问题语义...", "检索知识库...", "匹配最佳答案...", "生成处置方案..."],
};

export const employeeWorkflows = {
  resource: ["IP扫描", "设备识别", "服务探测", "资源建模"],
  fault: ["故障检测", "关联分析", "根因定位", "自动修复"],
  inspection: ["巡检计划", "执行检查", "健康评分", "报告生成"],
  order: ["工单解析", "智能分类", "自动分派", "处理跟踪"],
  query: ["查询解析", "SQL生成", "数据提取", "可视化"],
  knowledge: ["问题理解", "知识检索", "答案匹配", "方案生成"],
};

export const employeeResults = {
  resource: {
    title: "资源纳管完成",
    badge: "纳管成功",
    metrics: [
      { value: "2分38秒", label: "耗时", highlight: true },
      { value: "156", label: "发现" },
      { value: "143", label: "已纳管" },
      { value: "100%", label: "成功率" },
    ],
    resources: [
      { type: "network", icon: "fa-network-wired", name: "网络设备", desc: "核心交换机 12台", status: "已纳管" },
      { type: "server", icon: "fa-server", name: "服务器", desc: "10.0.1.x 网段", status: "已纳管" },
      { type: "middleware", icon: "fa-box", name: "中间件", desc: "Kafka/Redis", status: "已纳管" },
    ],
  },
  fault: {
    title: "故障已修复",
    badge: "恢复成功",
    metrics: [
      { value: "4分12秒", label: "MTTR", highlight: true },
      { value: "1个", label: "根因" },
      { value: "自动", label: "方式" },
      { value: "0影响", label: "业务" },
    ],
    resources: [],
  },
  inspection: {
    title: "巡检完成",
    badge: "评分98.5",
    metrics: [
      { value: "98.5分", label: "评分", highlight: true },
      { value: "156项", label: "检查" },
      { value: "3项", label: "异常" },
      { value: "8分钟", label: "耗时" },
    ],
    resources: [],
  },
  order: {
    title: "工单已处理",
    badge: "已关闭",
    metrics: [
      { value: "25秒", label: "耗时", highlight: true },
      { value: "1张", label: "已处理" },
      { value: "自动", label: "分派" },
      { value: "已关闭", label: "状态" },
    ],
    resources: [],
  },
  query: {
    title: "查询完成",
    badge: "数据就绪",
    metrics: [
      { value: "3秒", label: "耗时", highlight: true },
      { value: "15条", label: "记录" },
      { value: "PDF", label: "格式" },
      { value: "95%", label: "匹配" },
    ],
    resources: [],
  },
  knowledge: {
    title: "已解答",
    badge: "方案生成",
    metrics: [
      { value: "2秒", label: "响应", highlight: true },
      { value: "5条", label: "参考" },
      { value: "95%", label: "匹配" },
      { value: "3步", label: "操作" },
    ],
    resources: [],
  },
};

export const dashboardDailyTasks = [
  { id: 1, name: "自动巡检（全栈资源核查）", icon: "fa-clipboard-check", time: "08:00", status: "done", statusText: "已完成", action: "查看详情" },
  { id: 2, name: "OLT流量日报", icon: "fa-chart-line", time: "08:30", status: "running", statusText: "自动推送", action: "查看" },
  { id: 3, name: "MSE License 隐患复查", icon: "fa-exclamation-triangle", time: "09:15", status: "pending", statusText: "需确认", action: "确认" },
  { id: 4, name: "中继电路扩容审批", icon: "fa-file-signature", time: "10:00", status: "pending", statusText: "待处理", action: "一键审批" },
  { id: 5, name: "SRv6 Policy 优化评估", icon: "fa-cogs", time: "14:00", status: "pending", statusText: "自动执行", action: "—" },
  { id: 6, name: "生成日报并发送", icon: "fa-paper-plane", time: "16:00", status: "pending", statusText: "自动执行", action: "—" },
];

export const executionHistory = [
  { id: 1, time: "10:25:32", title: "IP扫描 10.0.1.0/24", detail: "发现设备 156 台，成功纳管 143 台", agent: "资产管家", agentIcon: "fa-server", status: "success" },
  { id: 2, time: "10:18:15", title: "故障自愈 - 数据库连接", detail: "自动重启连接池，恢复正常", agent: "故障速应", agentIcon: "fa-wrench", status: "success" },
  { id: 3, time: "10:12:08", title: "健康检查巡检", detail: "评分 98.5，发现 3 项异常", agent: "巡弋小卫", agentIcon: "fa-clipboard-check", status: "success" },
  { id: 4, time: "10:05:45", title: "工单自动分派", detail: "分派工单 WO-2024-0325-0089", agent: "工单管家", agentIcon: "fa-ticket-alt", status: "success" },
  { id: 5, time: "09:58:22", title: "性能报表生成", detail: "生成本周运维周报 PDF", agent: "数据洞察员", agentIcon: "fa-chart-bar", status: "success" },
  { id: 6, time: "09:45:10", title: "Redis 故障处理", detail: "缓存穿透问题，正在修复中", agent: "故障速应", agentIcon: "fa-wrench", status: "running" },
  { id: 7, time: "09:30:05", title: "知识问答查询", detail: "查询 Oracle 死锁解决方案", agent: "知库小典", agentIcon: "fa-book-open", status: "success" },
  { id: 8, time: "09:15:33", title: "网络设备扫描", detail: "扫描核心交换机 12 台", agent: "资产管家", agentIcon: "fa-server", status: "success" },
];

export function getEmployeeById(employeeId: string): DigitalEmployee {
  return digitalEmployees.find((item) => item.id === employeeId) || digitalEmployees[0];
}
