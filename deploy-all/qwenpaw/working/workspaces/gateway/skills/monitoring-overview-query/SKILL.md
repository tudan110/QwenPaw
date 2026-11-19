---
name: monitoring-overview-query
description: 查询监控总览/运维驾驶舱页面数据。适用于用户询问当前系统概览、智观系统运行状态、整体运行态势、监控概况、资产总览、应用健康概览、告警对象 Top5、全局/系统/监控/简易拓扑时使用。监控页中的实时告警时间范围查询继续使用 real-alarm；具体某个应用的 CMDB 关系拓扑继续使用 zgops-cmdb。
---

# Monitoring Overview Query

## 执行通道路由

先读取本轮系统提供的 **Skill execution routes**，按能力分别选择通道；下文 MCP 操作说明仅适用于该能力的 `mcp` 路由。

- `script`：MCP 已关闭或未配置，直接执行本技能已有脚本，不先尝试 MCP；记录 `mcp_disabled` / `mcp_not_configured`。
- `mcp`：调用已就绪的 MCP 工具；只有已确认的只读连接/传输失败或协议无法解析，才允许一次脚本回退。
- `unavailable`：加载中或状态未知，说明尚未就绪；不得把工具不可见推断为未配置或直接转脚本。仅 `reason=mcp_transport_unavailable` 明确确认了发现阶段的连接故障时，允许只读操作使用已有脚本一次；缺少路由摘要时也不猜测开关状态。
- `blocked`：权限、审批或工具白名单限制，不得通过脚本或跨智能体绕过。可解析的鉴权、参数、业务错误及成功空结果均不自动回退。
- 脚本缺失、依赖或凭据缺失时报告具体限制，不反向启用 MCP、不换身份。写操作已发送但结果不明时，不用脚本重复提交；通道切换不改变原有授权与通知规则。

查询监控总览/运维驾驶舱数据。面向"全局监控总览"和"系统级概览"，不需要用户先选择某个 CMDB 应用。

## MCP 通道说明

对应能力路由为 `mcp` 时使用 `resource` MCP Server（含监控总览工具）。`mcp` 路由下必须直接调用以下 MCP Tools；不要自行使用 `curl`、`requests`、SSE 或 JSON-RPC。

在对应能力为 `script`，或 `mcp` 路由满足上文只读故障回退条件时，才允许回退到旧脚本路径（见末尾"旧脚本回退路径"）。

## 边界

- 告警列表、实时告警、按时间范围查询告警：继续使用 `real-alarm`
- 数据库状态总览、资源性能 Top、数据库指标清单：继续使用 `resource-insight-query`
- CMDB count/group、模型分布、厂商分布：继续使用 `zgops-cmdb`
- 指定了具体应用名/项目名的应用关系拓扑：继续使用 `zgops-cmdb`
- 未指定具体应用的"简易拓扑 / 系统拓扑 / 全局拓扑 / 监控拓扑"：使用本技能的 `queryMonitoringTopology`

## MCP Tools

| 操作 | MCP Tool | 参数 |
| --- | --- | --- |
| 告警对象排行 | `resource__queryAlarmResourceTop` | `alarmClassType`, `alarmSeverity`, `type` |
| 监控拓扑 | `resource__queryMonitoringTopology` | 无 |
| 资产总览 | `resource__queryAssetOverview` | 无 |

## 自然语言映射

- "告警对象 top5 / 告警对象排行" → `resource__queryAlarmResourceTop`
- "系统概览 / 当前运行态势 / 监控概况 / 应用健康概览" → `resource__queryAssetOverview`
- "监控拓扑 / 简易拓扑 / 系统拓扑 / 全局拓扑 / 总览拓扑" → `resource__queryMonitoringTopology`，优先输出 `echarts` 代码块
- "资产总览 / 资源健康概览" → `resource__queryAssetOverview`
- "某某应用拓扑 / 指定应用依赖拓扑" → 不要用本技能，改用 `zgops-cmdb`
- "最近 24 小时实时告警" → 不要用本技能，改用 `real-alarm`

## 旧脚本回退路径

生产环境通过工具的 `cwd` 参数指定本技能目录，每次执行一条固定 Python 查询命令；不要拼接 `cd`、`&&` 或管道。


在对应能力为 `script`，或 `mcp` 路由满足上文只读故障回退条件时，才执行以下命令。脚本自动从环境变量读取凭证。

```bash
python3 scripts/monitoring_overview.py alarm-top5 --output markdown
python3 scripts/monitoring_overview.py topology --output markdown
python3 scripts/monitoring_overview.py asset-overview --output markdown
```

脚本通道或回退时必须在过程说明中写明真实路由原因（如 `resource-mcp-unavailable`）。