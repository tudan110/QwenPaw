---
name: order-workflow
category: workflow
tags: [order, workorder, workflow, ticket]
triggers: [工单, 工单统计, 待办工单, 已办工单, 工单详情, 创建工单, 处置工单]
description: inoe-ferry 工单技能：工单统计、待办/已办列表、工单详情、创建处置工单。
---

# Order Workflow

## 执行通道路由

先读取本轮系统提供的 **Skill execution routes**，按能力分别选择通道；下文 MCP 操作说明仅适用于该能力的 `mcp` 路由。

- `script`：MCP 已关闭或未配置，直接执行本技能已有脚本，不先尝试 MCP；记录 `mcp_disabled` / `mcp_not_configured`。
- `mcp`：调用已就绪的 MCP 工具；只有已确认的只读连接/传输失败或协议无法解析，才允许一次脚本回退。
- `unavailable`：加载中或状态未知，说明尚未就绪；不得把工具不可见推断为未配置或直接转脚本。仅 `reason=mcp_transport_unavailable` 明确确认了发现阶段的连接故障时，允许只读操作使用已有脚本一次；缺少路由摘要时也不猜测开关状态。
- `blocked`：权限、审批或工具白名单限制，不得通过脚本或跨智能体绕过。可解析的鉴权、参数、业务错误及成功空结果均不自动回退。
- 脚本缺失、依赖或凭据缺失时报告具体限制，不反向启用 MCP、不换身份。写操作已发送但结果不明时，不用脚本重复提交；通道切换不改变原有授权与通知规则。

对接 inoe-ferry 工单接口。告警派单、审批/流转等暂未接入，不要联动 `fault` skill。

## 工单 MCP 通道说明

对应能力路由为 `mcp` 时使用 `order` MCP Server。`mcp` 路由下必须直接调用以下 MCP Tools；不要自行使用 `curl`、`requests`、SSE 或 JSON-RPC，也不要为此编写额外 MCP 客户端。

在对应能力为 `script`，或 `mcp` 路由满足上文只读故障回退条件时，才允许回退到旧脚本路径（见末尾"旧脚本回退路径"）。

## 能力

| 操作 | MCP Tool | 说明 |
|---|---|---|
| 工单统计 | `order__getWorkOrderStats` | 传 `startTime` / `endTime` |
| 待办列表 | `order__listWorkOrders(classify=1)` | 分页参数 `page` / `per_page` |
| 已办列表 | `order__listWorkOrders(classify=5)` | 分页参数 `page` / `per_page` |
| 工单详情 | `order__getWorkOrderDetail` | 传 `processId` + `workOrderId` |
| 创建工单 | `order__createWorkOrder` | 按故障处置模板字段传参 |

## 工单 MCP 调用

### 参数映射

| 脚本原参数 | MCP 参数 | 说明 |
|---|---|---|
| `--begin-time` / `--end-time` | `startTime` / `endTime` | 直接对应 |
| `--page-num` / `--page-size` | `page` / `per_page` | 名称不同，值相同 |
| `classify=1` (待办) | `classify: 1` | 直接对应 |
| `classify=5` (已办) | `classify: 5` | 直接对应 |
| `--process-id` / `--work-order-id` | `processId` / `workOrderId` | 直接对应 |

### 场景 A：工单统计

```json
{
  "startTime": "<可选>",
  "endTime": "<可选>"
}
```

返回 `todoCount` / `inProgressCount` / `finishedCount`。

### 场景 B：待办/已办列表

```json
{
  "classify": 1,
  "page": 1,
  "per_page": 10
}
```

- 待办 `classify=1`，已办 `classify=5`
- 默认第 1 页 10 条预览；用户说"全部/全量"才逐页拉取
- 列表里的「工单号」「流程号」必须完整，禁止省略号缩写（查详情要用）

### 场景 C：工单详情

```json
{
  "processId": "<从上一条列表取流程号>",
  "workOrderId": "<从上一条列表取工单号>"
}
```

### 场景 D：创建工单

调用 `order__createWorkOrder`，按以下结构传参。必填：`alarm.alarmTitle` + (`alarm.neName` 或 `alarm.neIp` 至少一个)。

```json
{
  "alarm": {
    "alarmTitle": "<告警标题，必填>",
    "neName": "<设备名称>",
    "neIp": "<设备IP>",
    "alarmSeverity": "严重|主要|普通|预警",
    "isClear": "活跃告警|清除告警",
    "neTime": "<YYYY-MM-DD HH:MM:SS>",
    "sendTim": "<发现时间>",
    "vendor": "<厂家>",
    "neAlias": "<设备别名>",
    "alarmSeq": "<流水号>",
    "additionalText": "<告警原始报文>",
    "alarmLocation": "<定位信息>"
  },
  "analysis": {
    "summary": "<分析摘要>",
    "rootCause": "<根因分析结论>",
    "suggestions": ["<处置建议1>", "<处置建议2>"]
  },
  "ticket": {
    "title": "<工单标题>",
    "priority": "P1|P2|P3",
    "category": "<工单分类>",
    "source": "portal-order-agent",
    "externalSystem": "manual-workorder"
  }
}
```

**值转换规则（Agent 自行处理）**：

| 输入 | 转换为 |
|---|---|
| P1 / critical / 严重 / 紧急 | `alarmSeverity: "严重"` |
| P2 / major / 主要 / 重要 | `alarmSeverity: "主要"` |
| P3 / minor / 普通 / 一般 | `alarmSeverity: "普通"` |
| P4 / warning / 预警 | `alarmSeverity: "预警"` |
| 含"清除/恢复/clear/resolved" | `isClear: "清除告警"` |
| 否则 | `isClear: "活跃告警"` |
| "现在"/"now"/空 | `neTime: 当前时间` |
| 不给 sendTim | `sendTim: 取 neTime` |
| 严重 | `ticket.priority: "P1"` |
| 主要 | `ticket.priority: "P2"` |
| 普通/预警 | `ticket.priority: "P3"` |

**别名兼容**：`deviceName→neName`、`manageIp/ip→neIp`、`title→alarmTitle`、`level/priority→alarmSeverity`。

**创建规则**：
- 把用户每个输入放到对应字段，绝不要一股脑塞进 `suggestions`
- 只补问缺失的必填字段，别把内部 JSON 字段清单整段抛给用户
- 其余可选字段不给留空，别为凑字段逐个追问
- 完整字段/别名/值转换参考 `references/create-fields.md`

## 自然语言映射

- "待办/已办工单"：默认第 1 页 10 条预览；说"全部/全量"才全量查
- "看详情 / 第 N 条详情"：从上一条列表取「工单号」(workOrderId) 和「流程号」(processId)，执行 `order__getWorkOrderDetail`
- "创建工单"：按上面的字段映射整理参数后调用 `order__createWorkOrder`

## 返回要求

- 只走 markdown，不输出 `portal-visualization`
- 列表 10 条预览表带"序号"列，详情 markdown
- 列表里的「工单号」「流程号」必须完整，禁止省略号缩写
- 创建时只补问缺失的必填，别把内部 JSON 字段清单整段抛给用户

## 旧脚本回退路径

在对应能力为 `script`，或 `mcp` 路由满足上文只读故障回退条件时，才执行以下命令。脚本自动从环境变量读取凭证（由设置页热加载），无需手动配置。

```bash
cd skills/order-workflow
python3 scripts/order_workflow.py stats --output markdown
python3 scripts/order_workflow.py todo-list --output markdown
python3 scripts/order_workflow.py finished-list --output markdown
python3 scripts/order_workflow.py detail --process-id <processId> --work-order-id <workOrderId> --output markdown
python3 scripts/order_workflow.py create --payload-file /tmp/order_create_payload.json --output markdown
```

脚本通道或回退时必须在过程说明中写明真实路由原因（如 `order-mcp-unavailable`）。