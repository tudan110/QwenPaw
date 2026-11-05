---
name: zgops-cmdb
description: 查询当前配置所指向的 CMDB 环境。用于模型、属性、关系、应用/资源拓扑、CMDB 资源数量和资源告警状态统计、厂商分布、count/group 类查询。监控运行状态总览和性能指标使用对应的监控/巡检技能。
---

# ZGOPS CMDB 查询技能

仅面向当前配置所指向的 CMDB 环境。

## CMDB MCP 优先级

本工作区已启用 `cmdb-query` MCP Server。查询时直接调用下面的数据工具；有CI ID先查详情/关系，没有唯一对象先搜索。**不先调用 `cmdb-query__cmdbLogin`，也不先运行登录脚本或client.login**，不能把登录成功当作只读MCP查询前提。不要自行使用 `curl`、`requests`、SSE、JSON-RPC或额外客户端，不使用浏览器代查。

仅在 cmdb-query MCP Driver 未加载、工具缺失、连接/传输不可用或协议无法解析时，才回退到旧脚本路径。可解析的空结果、参数错误、鉴权/权限或业务4xx/5xx必须fail-fast并说明，不以脚本换身份绕过，不换参数反复试探。登录参数错误不证明数据MCP不可用，也不是转脚本的理由。

## MCP Tools

| 操作 | MCP Tool | 参数 | 说明 |
| --- | --- | --- | --- |
| 查 CI 类型列表 | `cmdb-query__listCiTypes` | `page`, `per_page` | 读取 `ci_types`；模型 `name` 是查询标识，返回数已达到 `numfound` 时不继续翻页 |
| 查 CI 类型属性 | `cmdb-query__getCiTypeAttributes` | `id` | 模型 ID 按 schema 转字符串；用于确认真实字段、唯一键 |
| 查 CI 显示属性 | `cmdb-query__getCiTypePreferenceAttributes` | `id` | 模型 ID；显示偏好不等于完整属性定义 |
| 查属性目录 | `cmdb-query__listAttributes` | `page`, `page_size` | 全局属性目录，不能当作 CI 实例列表 |
| 查 CI 类型关系 | `cmdb-query__listCiTypeRelations` | `ci_type_id` | 模型关系定义，不是实例关系；可选 ID 按 schema 传参 |
| 查 CI 父类型关系 | `cmdb-query__getCiTypeParentRelations` | `id` | 模型 ID；父类型定义不能证明具体实例已关联 |
| 查 CI 类型分组 | `cmdb-query__listCiTypeGroups` | — | 返回类型分组目录 |
| 查 CI 关系类型 | `cmdb-query__listRelationTypes` | — | 返回所有关系类型 |
| 查 CMDB 类型 | `cmdb-query__listCmdbTypes` | — | 返回 CMDB 类型列表 |
| 搜索 CI 实例 | `cmdb-query__searchCiInstances` | `q`, `page`, `count` | `q=_type:<模型名>` 按类型搜索 |
| 查 CI 实例详情 | `cmdb-query__getCiInstance` | `id` | CI 的 `_id` 按 schema 转字符串；当前返回 `ci_id` + `ci`，不是 `result` |
| 查 CI 关系拓扑 | `cmdb-query__getCiRelations` | `root_id`, `level`, `count`, `reverse` | `reverse` 为可选整数，默认 `0`：root 作父节点查下游；`1`：root 作子节点查上游 |
| 登录 | `cmdb-query__cmdbLogin` | — | 获取会话 token（通常只读查询不需要） |
| 查用户信息 | `cmdb-query__getCmdbUserInfo` | — | — |
| 分组资源状态统计 | `cmdb-query__countCi` | `type`（必填） | `CITypeGroup.id`，返回该资源分组的总数和告警状态数，不是全量 CMDB 数量 |
| 模型属性数量分布 | `cmdb-query__countCiByAttribute` | `type`, `attr`（必填） | 模型 ID + 属性名，返回 `type/count` 行；先检查下述 schema 兼容说明 |
| 分组内模型状态分布 | `cmdb-query__countCiByGroup` | `type`（必填） | 目标分组 ID；当前服务也接受模型 ID，但重号时有歧义，单模型优先用 `countChildCi` |
| 单模型资源状态统计 | `cmdb-query__countChildCi` | `type`（必填） | `CIType.id`，不能传模型分组 ID |
| 单模型属性状态分布 | `cmdb-query__countChildCiByGroup` | `type`, `attr`（必填） | 模型 ID + 属性名，返回资源状态数量；先检查 schema 兼容说明 |

### 参数与响应契约

- `_id` 是 CI 实例 ID；`_type` 是数字模型 ID；`ci_type` 是真实模型名称；`ci_type_alias` 是显示别名。不要把数字 `_type` 或显示别名当 `metricType`。详情先读取 `ci`，旧版 `result` 只作兼容。
- 查询字段来自模型属性/唯一键，不把 `Server`、`hostname` 或旧版 `middleware_name`、`db_instance` 当作所有模型的固定字段。完整语法及返回结构见 `references/endpoints.md`。
- 搜索响应的 `numfound` 是总匹配数，`total` 是本页数量。按实际返回 CI 数与 `numfound` 判断是否取全，逐页去重；不能用本页 `total` 作为全量数量。
- 当前 `getCiRelations` 只有 `root_id/level/count/reverse`，不要传未声明的 `page/fl/excludes`。`count=10000` 不保证完整；达到数量限制或少于 `numfound` 时明确标注截断，不转脚本绕过成功结果。
- 当前两项属性统计工具把 `attr` 声明为 integer，但接口语义是 `"vendor"` 等属性名。先检查实际 schema；若仍不能表达属性名，明确报告工具声明不兼容，不强传字符串、猜属性 ID 或用脚本绕过。普通业务错误仍 fail-fast。
- 数量、资源告警状态数量、告警事件条数和巡检指标是不同口径；统计结果中的 `resourceType/resourceClass` 不能直接当作指标模型名。

## 常见场景

### 按类型查资源实例

1. 调用 `cmdb-query__listCiTypes`，按响应判断是否已取全，找到实际模型的 `name`（如 `redis`、`mysql`）
2. 调用 `cmdb-query__searchCiInstances(q="_type:<模型名>", page=1, count=100)` 搜索实例
3. 多实例时列出候选让用户选择，禁止自动任选
4. 唯一确认后读取实例详情的 `ci`；`_id` 才是 `resId`，`ci_type` 才是模型名称。只有 `_type` 时通过模型目录解析，不根据告警标题或其他关联资源猜模型。

已知 CI ID 时直接确认详情，不必先列出整个模型目录。批量补齐已确认的关联 CI 可用 `q="_id:(ID1;ID2;ID3)"`（分号分隔），不能在多候选定位时自动任选。

### 查应用拓扑

1. "找某个应用" → 调用 `cmdb-query__searchCiInstances(q="_type:project")`，本地过滤名称
2. 唯一命中后 → 调用 `getCiRelations(root_id=<应用_ci_id>, level=1, count=10000)`；需要第二、三层时分别再传 `level=2`、`level=3`。保持默认正向；`level=2` 不包含第一层。
3. 合并去重后输出 ECharts 从左到右关联资源概览（`series.type='tree'`），根节点用实际应用名。只有已确认实例关系边/路径时才称为部署链；CI 列表本身不是完整边列表。

应用拓扑保持默认正向查询，不自动追加反向关系；旧 `app-topology` 脚本仍只接受应用名，不用于资源实例上游查询。

### 查资源实例拓扑

1. 已知 CI ID 时先用 `getCiInstance` 确认实例；否则先搜索并确认唯一目标，多候选让用户选择。
2. 对同一个 `root_id` 先用 `reverse=0` 查下游，再用 `reverse=1` 查上游，`count=10000`。两方向均覆盖 `level=1..3`：当前 MCP 只接受整数，分别查询 `level=1`、`level=2`、`level=3`；它们是独立层级，不是累计深度。HTTP 回退脚本使用单个 `level=1,2,3`，不能重复写 `level=1&level=2&level=3`（只取第一个值）。
3. 合并两方向结果：节点按 CI ID 去重；关系优先按关系 ID 去重，没有关系 ID 时按 `(源 CI ID, 目标 CI ID, 关系类型)` 去重。保留 `forward/reverse` 查询来源，不反转真实关系边。若接口只有节点列表，没有边端点/关系类型，就明确说明，不能把节点列表当完整关系图或补造边。
4. mysql、redis 等叶子节点正向为空属正常，只能说明未查到下游，不能据此下“无关系”结论。仅当正反向都成功且为空，才说明“本次层级和数量限制内未发现关系”。这些是预先计划的互补查询，不是业务错误后的换参数重试；任一方向失败时停止并报告已取得结果及拓扑不完整，不用空列表代替错误，不转脚本绕过错误。
5. 有已确认实例边/路径时按真实方向输出，单父树可用 `tree`，多父、共享节点或环用 `graph`。只有 CI 列表时画“关联资源概览”并注明没有完整边信息，不按同 IP、只有一台虚拟机或模型关系定义补造部署链；不把第二层 CI 任意挂到某个第一层节点。关系类型没有返回时不要默认写 `contain/deploy`。

### 统计分析

| 用户意图 | MCP 调用 | 输出 |
| --- | --- | --- |
| 某资源分组的数量/告警状态分布 | `listCiTypeGroups` 确认分组 → `countCi(type=<分组ID>)` | 资源状态表，不是事件条数 |
| 分组内各模型资源状态 | `countCiByGroup(type=<分组ID>)` | 表格/分布图 |
| 单模型资源状态 | `countChildCi(type=<模型ID>)` | 表格 |
| 单模型厂商等属性的纯数量分布 | 确认属性名及 schema → `countCiByAttribute(type=<模型ID>, attr=<属性名>)` | 使用返回的 `count`，不是 `total` |
| 单模型属性的资源告警状态分布 | 确认属性名及 schema → `countChildCiByGroup(type=<模型ID>, attr=<属性名>)` | 状态表/图 |

先按当前元数据区分模型分组与具体模型，不能固定数据库/中间件等 ID，也不能统一“分组优先”。新名称如“软件服务-中间件”仍需确认其实际分组和成员；多候选让用户选择。分组与模型可能重号，单模型优先用 child 接口。分组属性分布需要分别查询成员模型后按属性值合并，不能把分组 ID 塞进模型属性统计接口。

成功但属性分组为空只说明没有该属性的分组数据，不代表没有资源。当前资源的监控运行状态总览/性能使用 `resource-insight-query`；告警事件使用 `real-alarm`；CMDB count/group 结果留在本技能。

### 应用拓扑

- 用户说"某个应用的关系拓扑/架构关系图" → 先 `cmdb-query__searchCiInstances(q="_type:project")` 确认目标，再 `cmdb-query__getCiRelations`
- 用户只说"简易拓扑/系统拓扑/全局拓扑"且无应用名 → 这不是 CMDB 拓扑，交给 `monitoring-overview-query`
- 多应用时先列出候选让用户选择，不要默认任选

## 输出风格

- 模型列表：`ID / 名称 / 别名 / 唯一键` 表格
- 单模型：关键字段和关键关系
- 图表：ECharts，饼图用于分布占比，柱状图用于数量对比
- 应用拓扑：从左到右树状图，根节点放应用；资源拓扑以实际资源为中心，保留上游到资源、资源到下游的真实方向，多父关系用 `graph`
- 不要生成 `.html` 文件，直接输出 ```echarts 代码块
- 回复中不要出现 `ZGOPS`、`zgops`、`OneOps` 等产品字样
- 默认返回精简总结，只有用户明确要求时才返回原始 JSON
- 原始 JSON、错误信息、图表和脚本输出也要脱敏；`bearer_token`、`login_pwd`、password、token、API key 等凭证不得原样回显。MCP 返回即使包含凭证，也不得复制到回复、图表、日志或文件。

## 旧脚本回退路径

仅当 cmdb-query MCP Driver 未加载、客户端/工具不可用或协议响应无法解析时，才执行以下命令。脚本自动从环境变量读取凭证（由设置页热加载）。

```bash
scripts/zgops-cmdb.sh list-models
scripts/zgops-cmdb.sh fetch "/api/v0.1/ci/s?q=_type:<name>&page=1&count=100"
scripts/zgops-cmdb.sh fetch "/api/v0.1/ci_relations/s?root_id=<ci_id>&level=1,2,3&count=10000&page=1"
scripts/zgops-cmdb.sh fetch "/api/v0.1/ci_relations/s?root_id=<ci_id>&level=1,2,3&count=10000&page=1&reverse=1"
scripts/zgops-cmdb.sh find-project <应用名>
scripts/zgops-cmdb.sh app-topology <应用名>
scripts/zgops-cmdb.sh analyze --mode summary --output markdown
scripts/zgops-cmdb.sh inoe-stat types --output markdown
scripts/zgops-cmdb.sh inoe-stat group --resource_type middleware --attr vendor --output markdown
scripts/zgops-cmdb.sh inoe-stat child --type_id <模型ID> --type_kind model --output markdown
scripts/zgops-cmdb.sh inoe-stat group-attr --type_id <模型ID> --type_kind model --attr vendor --output markdown
```

回退时必须在过程说明中写明回退原因（如 `cmdb-query-mcp-unavailable`）。

回退响应按 HTTP 状态和 `code/msg/message` 判断成功，失败不能当空结果；关联搜索仍需按 `numfound` 翻页。`inoe-stat` 默认动态解析元数据，`--no_dynamic_type` 只能与明确的 `--type_id`、`--type_kind` 配合，不再猜环境 ID。目录有歧义时停止；分组属性统计按成员模型查询并合并。

## 备注

- 这套环境中 `project` 对应"应用"模型
- 凭据由设置页统一管理，MCP 路径无需任何配置
- 如需图表规范，读取 `references/chart-guide.md` 或 `references/echarts-examples.md`
- 如果用户要做资源导入/纳管/批量导入，改用同级 `zgops-cmdb-import` skill