---
name: resource-insight-query
description: 查询 INOE 资源状态与性能数据。适用于用户询问设备状态统计、数据库状态总览、资源性能 Top、CPU/内存/磁盘/响应时间等性能排行、数据库性能指标清单时使用。告警列表和告警统计继续使用 real-alarm；CMDB 模型/关系/ci count 查询继续使用 zgops-cmdb。
---

# Resource Insight Query

## 执行通道路由

先读取本轮系统提供的 **Skill execution routes**，按能力分别选择通道；下文 MCP 操作说明仅适用于该能力的 `mcp` 路由。

- `script`：MCP 已关闭或未配置，直接执行本技能已有脚本，不先尝试 MCP；记录 `mcp_disabled` / `mcp_not_configured`。
- `mcp`：调用已就绪的 MCP 工具；只有已确认的只读连接/传输失败或协议无法解析，才允许一次脚本回退。
- `unavailable`：加载中或状态未知，说明尚未就绪；不得把工具不可见推断为未配置或直接转脚本。仅 `reason=mcp_transport_unavailable` 明确确认了发现阶段的连接故障时，允许只读操作使用已有脚本一次；缺少路由摘要时也不猜测开关状态。
- `blocked`：权限、审批或工具白名单限制，不得通过脚本或跨智能体绕过。可解析的鉴权、参数、业务错误及成功空结果均不自动回退。
- 脚本缺失、依赖或凭据缺失时报告具体限制，不反向启用 MCP、不换身份。写操作已发送但结果不明时，不用脚本重复提交；通道切换不改变原有授权与通知规则。

查询 INOE 资源状态与性能数据。不处理实时告警列表，也不替代 `zgops-cmdb`。

## MCP 通道说明

对应能力路由为 `mcp` 时使用 `resource` MCP Server。`mcp` 路由下必须直接调用以下 MCP Tools；不要自行使用 `curl`、`requests`、SSE 或 JSON-RPC。

在对应能力为 `script`，或 `mcp` 路由满足上文只读故障回退条件时，才允许回退到旧脚本路径（见末尾"旧脚本回退路径"）。

## 边界

- 实时告警列表、告警级别统计、当前告警详情：使用 `real-alarm`
- CMDB 模型、CI 列表、CI 关系、count 类接口：使用 `zgops-cmdb`
- 资源状态总览、性能 Top、数据库指标清单：使用本技能

## MCP Tools

| 操作 | MCP Tool | 参数 |
| --- | --- | --- |
| 数据库状态总览 | `resource__getDatabaseResourceStatusOverview` | 无 |
| 页面性能 Top | `resource__getTopMetricData` | `orderCode`, `topNum`, `type` |
| 资源性能 Top | `resource__getTopResourceMetricData` | `orderKey`, `topNum`, `type` |
| 数据库性能指标 | `resource__queryDatabasePerformanceMetrics` | `keyWord`, `pageNum`, `pageSize` |

## 自然语言映射

- "数据库状态总览 / 数据库状态统计" → `resource__getDatabaseResourceStatusOverview`
- "数据库性能 Top / 磁盘使用率排行" → `resource__getTopMetricData(orderCode="diskRate", topNum=5)`
- "网络设备性能 / CPU 排行" → `resource__getTopResourceMetricData(orderKey="cpuRate", topNum=5)`
- "操作系统性能 / 服务器性能" → `resource__getTopResourceMetricData(type="os" 或 "server")`
- "主机磁盘使用率排行 / 磁盘 Top" → `resource__getTopResourceMetricData(orderKey="diskRate", topNum=5)`
- "列出磁盘使用率超 80% 的主机" → 调对应 MCP Tool 获取数据后，本地过滤
- "数据库性能指标清单" → `resource__queryDatabasePerformanceMetrics(pageNum=1, pageSize=20)`
- "资源概览汇总" → 组合调用上述 MCP Tools 后自行汇总

## 旧脚本回退路径

生产环境通过工具的 `cwd` 参数指定本技能目录，每次执行一条固定 Python 查询命令；不要拼接 `cd`、`&&` 或管道。


在对应能力为 `script`，或 `mcp` 路由满足上文只读故障回退条件时，才执行以下命令。脚本自动从环境变量读取凭证。

```bash
python3 scripts/resource_insight.py status-overview --resource_type database --output markdown
python3 scripts/resource_insight.py top-metric --resource_type database --top_num 5 --output markdown
python3 scripts/resource_insight.py summary --resource_type database --output markdown
```

脚本通道或回退时必须在过程说明中写明真实路由原因（如 `resource-mcp-unavailable`）。