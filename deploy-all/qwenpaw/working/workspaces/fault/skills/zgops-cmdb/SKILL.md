---
name: zgops-cmdb
description: 用于查询当前配置所指向的 CMDB 环境。当用户询问模型、关系、层级、IPAM、DCIM、应用拓扑、资源拓扑、资源数量统计、资源状态统计、制造商/厂商分布、CMDB count/group 类接口时使用。
---

# ZGOPS CMDB 查询技能

仅面向当前配置所指向的 CMDB 环境。

## CMDB MCP 优先级

本工作区已启用 `cmdb-query` MCP Server。查询时直接调用下面的数据工具；有CI ID先查详情/关系，没有唯一对象先搜索。**不先调用 `cmdb-query__cmdbLogin`，也不先运行登录脚本或client.login**，不能把登录成功当作只读MCP查询前提。不要自行使用 `curl`、`requests`、SSE、JSON-RPC或额外客户端，不使用浏览器代查。

仅在 cmdb-query MCP Driver 未加载、工具缺失、连接/传输不可用或协议无法解析时，才回退到旧脚本路径。可解析的空结果、参数错误、鉴权/权限或业务4xx/5xx必须fail-fast并说明，不以脚本换身份绕过，不换参数反复试探。登录参数错误不证明数据MCP不可用，也不是转脚本的理由。

## MCP Tools

| 操作 | MCP Tool | 参数 | 说明 |
| --- | --- | --- | --- |
| 查 CI 类型列表 | `cmdb-query__listCiTypes` | `page`, `per_page` | 分页取全，模型 `name` 是后续查询标识 |
| 查 CI 类型属性 | `cmdb-query__getCiTypeAttributes` | `id` | 传 CI 类型 ID |
| 查 CI 类型关系 | `cmdb-query__listCiTypeRelations` | `ci_type_id` | 传 CI 类型 ID |
| 查 CI 类型分组 | `cmdb-query__listCiTypeGroups` | — | 返回类型分组目录 |
| 查 CI 关系类型 | `cmdb-query__listRelationTypes` | — | 返回所有关系类型 |
| 查 CMDB 类型 | `cmdb-query__listCmdbTypes` | — | 返回 CMDB 类型列表 |
| 搜索 CI 实例 | `cmdb-query__searchCiInstances` | `q`, `page`, `count` | `q=_type:<模型名>` 按类型搜索 |
| 查 CI 实例详情 | `cmdb-query__getCiInstance` | `id` | 传 CI 的 `_id` |
| 查 CI 关系拓扑 | `cmdb-query__getCiRelations` | `root_id`, `level`, `count` | 查上下游关系链 |
| 查用户信息 | `cmdb-query__getCmdbUserInfo` | — | — |
| CI 数量统计 | `cmdb-query__countCi` | — | 全量 CI 数量 |
| CI 属性分组统计 | `cmdb-query__countCiByAttribute` | — | 按属性分组计数 |
| CI 分组统计 | `cmdb-query__countCiByGroup` | — | 按 CI 类型分组计数 |
| CI 子类型统计 | `cmdb-query__countChildCi` | — | 子类型数量 |
| CI 子类型分组统计 | `cmdb-query__countChildCiByGroup` | — | 子类型按属性分组 |

## 常见场景

### 按类型查资源实例

1. 调用 `cmdb-query__listCiTypes`，分页取全，找到目标模型的 `name`（如 `redis`、`mysql`）
2. 调用 `cmdb-query__searchCiInstances(q="_type:<模型名>", page=1, count=100)` 搜索实例
3. 多实例时列出候选让用户选择，禁止自动任选
4. 返回结果中 `_id` 是 CI ID（即 `resId`），`_type` 是 `ciType`

### 查应用拓扑

1. "找某个应用" → 调用 `cmdb-query__searchCiInstances(q="_type:project")`，本地过滤名称
2. 唯一命中后 → 调用 `cmdb-query__getCiRelations(root_id=<应用_ci_id>, level=1, count=10000)`
3. 输出 ECharts 从左到右树状图（`series.type='tree'`），根节点用实际应用名

### 统计分析

| 用户意图 | MCP 调用 | 输出 |
| --- | --- | --- |
| 资源类型分布 | `cmdb-query__countCiByGroup` | 饼图 |
| 按厂商分布 | `cmdb-query__countCiByAttribute` + 本地过滤 `vendor` | 柱状图 |
| 子类型统计 | `cmdb-query__countChildCi` | 表格 |
| 子类型分组 | `cmdb-query__countChildCiByGroup` | 饼图/柱状图 |

### 应用拓扑

- 用户说"某个应用的关系拓扑/架构关系图" → 先 `cmdb-query__searchCiInstances(q="_type:project")` 确认目标，再 `cmdb-query__getCiRelations`
- 用户只说"简易拓扑/系统拓扑/全局拓扑"且无应用名 → 这不是 CMDB 拓扑，交给 `monitoring-overview-query`
- 多应用时先列出候选让用户选择，不要默认任选

## 输出风格

- 模型列表：`ID / 名称 / 别名 / 唯一键` 表格
- 单模型：关键字段和关键关系
- 图表：ECharts，饼图用于分布占比，柱状图用于数量对比
- 关系拓扑：从左到右树状图，根节点放应用
- 不要生成 `.html` 文件，直接输出 ```echarts 代码块
- 回复中不要出现 `ZGOPS`、`zgops`、`OneOps` 等产品字样
- 默认返回精简总结，只有用户明确要求时才返回原始 JSON

## 旧脚本回退路径

仅当 cmdb-query MCP Driver 未加载、客户端/工具不可用或协议响应无法解析时，才执行以下命令。脚本自动从环境变量读取凭证（由设置页热加载）。

```bash
scripts/zgops-cmdb.sh list-models
scripts/zgops-cmdb.sh fetch "/api/v0.1/ci/s?q=_type:<name>&page=1&count=100"
scripts/zgops-cmdb.sh fetch "/api/v0.1/ci_relations/s?root_id=<ci_id>&level=1&level=2&level=3&count=10000"
scripts/zgops-cmdb.sh find-project <应用名>
scripts/zgops-cmdb.sh app-topology <应用名>
scripts/zgops-cmdb.sh analyze --mode summary --output markdown
scripts/zgops-cmdb.sh inoe-stat types --output markdown
scripts/zgops-cmdb.sh inoe-stat group --resource_type middleware --attr vendor --output markdown
```

回退时必须在过程说明中写明回退原因（如 `cmdb-query-mcp-unavailable`）。

## 备注

- 这套环境中 `project` 对应"应用"模型
- 凭据由设置页统一管理，MCP 路径无需任何配置
- `cmdb-query__cmdbLogin` 不属于本技能默认查询流程；仅用户明确要求认证操作时按实际工具schema及授权处理，不空参数试调用、不猜凭据，失败也不影响对可用数据工具的独立判断
- 如需图表规范，读取 `references/chart-guide.md` 或 `references/echarts-examples.md`
- 如果用户要做资源导入/纳管/批量导入，改用同级 `zgops-cmdb-import` skill