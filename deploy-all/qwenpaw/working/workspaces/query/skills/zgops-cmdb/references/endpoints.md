# CMDB 查询接口契约

本参考结合接口文档和当前服务实测整理。自动生成文档中的占位返回、源码片段和示例 ID 不是完整契约；跨环境时以实际 MCP schema、模型元数据及响应为准，不固定资源 ID、模型数量或分组 ID。

## 入口与范围

- 平台入口来自设置页物化的 `INOE_API_BASE_URL`，CMDB 路径为 `/cmdb/api/v0.1/`。
- `INOE_CMDB_API_BASE_URL` 若明确指向 `/cmdb`，不要再次拼接 `/cmdb`。
- 鉴权沿用已有平台配置，不把登录成功作为普通只读查询前置条件。
- 这里只用于查询。资源创建、修改、删除、纳管交给 `zgops-cmdb-import`；不能因为接口使用 GET 就自动执行发现同步、缓存刷新或其他管理动作。
- MCP 优先；只有技能规定的不可用/协议失败条件才回退已有脚本，不能用原生 HTTP 绕过可解析业务错误或参数 schema。

## 模型、分组与实例

| 对象 | 标识 | 用途 |
| --- | --- | --- |
| CI 实例 | `_id` | `resId`、详情查询 ID、拓扑 `root_id` |
| 具体模型 | `_type` / `CIType.id` | 数字模型 ID，用于模型元数据和 child 统计 |
| 模型名称 | `ci_type` / 模型目录的 `name` | `_type:<模型名>` 搜索，指标 `metricType` |
| 模型显示名 | `ci_type_alias` / `alias` | 展示，不能代替模型名称 |
| 模型分组 | `CITypeGroup.id` | count 分组统计，不等于模型 ID |

`GET /api/v0.1/ci_types` 当前返回 `ci_types` 列表和 `numfound`。`GET /api/v0.1/ci_types/groups` 当前直接返回分组数组，成员在 `ci_types`。脚本兼容旧版包装，但不能把目录错误当作空目录，也不能使用固定 ID 兜底。

模型目录已返回 `numfound` 对应的全部对象时停止，不因为工具有 `page/per_page` 就反复取相同目录。名称、分组或 ID 有歧义时列候选；“软件服务-中间件”之类的新分组名称必须从实际目录解析，不能照搬旧分组号。

完整字段、唯一键由 `GET /api/v0.1/ci_types/<模型ID>/attributes` 确认。显示偏好不等于完整模型定义。

## CI 详情与搜索

### 实例详情

`GET /api/v0.1/ci/<CI_ID>` 支持 `fields`、`ret_key`。当前返回：

```json
{
  "ci_id": 123,
  "ci": {
    "_id": 123,
    "_type": 61,
    "ci_type": "redis",
    "name": "示例资源"
  }
}
```

这些 ID 仅为结构示例。先读取 `ci`，旧 `result` 字典或裸 CI 仅作兼容。只有数字 `_type` 时从模型目录映射名称，不从告警标题、显示别名或其他关联资源猜 `metricType`。

### 实例搜索

`GET /api/v0.1/ci/s` 支持 `q/page/count`，以及 HTTP 层的 `fl/excludes/ret_key/sort/facet`。MCP 当前只暴露 `q/page/count`，不能自行添加其他参数。

| 语法 | 用途 | 状态 |
| --- | --- | --- |
| `_type:redis` | 按实际模型名查询 | 已实测 |
| `_id:123` | 单个 ID | 文档说明；已知 ID 优先详情确认 |
| `_id:(123;124;125)` | 批量 ID，分号分隔 | 已实测 |
| `字段名:值` | 按属性等值查询 | 字段来自元数据，不把它称为模糊搜索 |
| `字段名:(值1;值2)` | 属性 IN 查询 | 文档语法，目标环境使用前核验 |
| `字段名:[开始_TO_结束]` | 范围查询 | 文档语法，目标环境使用前核验 |
| `字段名:>值` / `字段名:<值` | 大于/小于 | 文档语法，目标环境使用前核验 |
| `+字段名:值` / `-字段名:值` / `~字段名:值` | 文档中的 AND/OR/NOT LIKE | 组合语法、转义和优先级尚需核验，不猜表达式 |

字段名来自模型属性/唯一键。当前部分中间件、数据库使用 `name`，不能默认固定 `middleware_name/db_instance`。HTTP 回退可选择已确认的字段，`fl=name` 会保留标识和模型信息；不要投影未经确认的属性，否则可能返回非 CI 对象。

### 分页

搜索和关系查询当前响应：

```json
{
  "numfound": 4,
  "total": 1,
  "page": 1,
  "result": [{"_id": 123, "ci_type": "redis", "name": "示例资源"}]
}
```

- `numfound` 是总匹配 CI 数，`total` 是本页数量。
- 按实例 ID 合并去重，读到全部 `numfound` 才算该范围取全；分页无进展或提前空页时标注不完整，不宣称无关系。
- 旧版未提供 `numfound` 时，已有脚本按实际分页结果读到尾页，不能把 `total` 一律当全量数量。
- `count=10000` 不是完整保证。MCP 未提供分页能力时不能传未声明的 `page` 或换脚本绕过成功结果，应报告截断。

## 关系查询

`GET /api/v0.1/ci_relations/s` 当前支持：

| 参数 | 语义 |
| --- | --- |
| `root_id` | 已确认 CI 实例 ID |
| `level` | 默认 1；指定层级、非累计深度 |
| `reverse` | 缺省/0：父节点向下；1：子节点向上 |
| `page/count` | HTTP 分页 |
| `q/fl/facet/sort` | 文档列出的 HTTP 查询参数；`excludes` 已验证用于 CI 搜索，不推定关系接口也支持 |
| `ancestor_ids/descendant_ids/root_parent_path/has_m2m` | 文档列出但语义和格式不完整，本技能不猜值 |

### 多层语义

- `level=2` 只返回第二层，不包含第一层。
- HTTP 多层用一个 `level=1,2,3`；重复 `level=1&level=2&level=3` 只取第一个值，会漏第二、三层。
- 当前 MCP 的 `level` 是 integer，分别查询 1、2、3 后合并，不传逗号字符串或数组。
- 指定层级为空，也可能与该层对应的模型关系定义有关；不能扩展成现实中没有依赖。
- 应用默认正向；资源实例按计划查询正反方向。任一方向失败则记录已取得结果和缺口，不重试猜参数。
- HTTP 资源上游示例：`/api/v0.1/ci_relations/s?root_id=<CI_ID>&level=1,2,3&reverse=1&count=10000&page=1`。

### CI 列表不等于关系边

关系搜索当前返回 `result` 中的 CI 对象，未包含完整实例边/路径及关系 ID。查询方向用于标记来源，不反转真实父子边。

只有节点时展示“关联资源概览”，不能按 IP、仅有一台虚拟机或模型允许的关系推造部署链；第二层节点不能任意挂到第一层节点。关系类型未返回时不要默认标 `contain/deploy`。

文档另列直接父/子查询、类型路径和实例路径接口，但当前 MCP 未全部暴露，不能默认为可用：

- `GET /api/v0.1/ci_relations/<CI_ID>/first_cis`：直接父 CI，当前响应为 `first_cis`。
- `GET /api/v0.1/ci_relations/<CI_ID>/second_cis`：子 CI，文档响应为 `second_cis`。
- `GET /api/v0.1/ci_type_relations/<模型ID>/parents`：模型父关系，不证明实例之间已关联。
- `POST /api/v0.1/ci_relations/path/s`：文档列出实例路径查询，需要单独确认工具与返回契约，不作为自动新增步骤。

## 统计接口

| HTTP 路径 | ID 语义 | 输出 |
| --- | --- | --- |
| `/ci/count` | 模型分组 ID | 分组资源总数及告警状态数 |
| `/ci/count/group` | 当前服务支持分组或模型 ID，但重号有歧义 | 分组内模型或属性的资源状态行 |
| `/ci/count/child` | 具体模型 ID | 单模型资源状态对象 |
| `/ci/count/child/group` | 具体模型 ID + 必填属性名 | 按属性值分组的资源状态行 |
| `/ci/count/group/attr` | 具体模型 ID + 必填属性名 | `type/count` 纯数量行 |

所有路径在 `/api/v0.1` 下。单模型优先使用 child 端点，避免把同号模型误查成分组；分组属性统计逐个查询实际成员模型后按属性值合并。无候选/多候选或元数据失败时停止，不使用旧环境数字兜底。

`inoe-stat` 的 `--type_kind group|model` 用于明确 ID 类型；`--no_dynamic_type` 必须同时提供 `--type_id` 和 `--type_kind`。明确的模型 `count/group` 请求会使用模型 child 端点，查询记录显示实际接口。

当前属性统计 MCP schema 的 `attr` 声明为 integer，而接口使用 `"vendor"` 等属性名。若 schema 尚未修正，报告声明不兼容，不猜属性 ID，不强传字符串或绕过工具。

资源状态统计返回 `code/msg/data`，其中有 `total/normalCount/warningCount/minorCount/severeCount/emergencyCount/unmonitoredCount`。紧急数不是总告警事件数；字段未返回时不填造零值。纯数量统计使用 `count` 画图，不能读不存在的 `total`。

属性分组为空不代表资源为空；模型数量来自模型目录，不来自资源 count。运行状态总览/性能和告警事件仍由对应监控技能处理。

## 错误与能力边界

- HTTP 状态、MCP `isError` 和业务 `code` 都要检查，HTTP 200 不等于业务成功。
- 错误可能是 `message`，也可能是 `code/msg`；保留具体缺口，不把解析失败当空列表。
- HTTP 500 也可能由模型/分组 ID 用错导致；先正确解析元数据，不换 ID 或接口反复试探。
- 现有输出安全规则继续适用，原始 JSON、错误和图表也不回显凭证。
- 变更历史、资源趋势、容器专项统计、DCIM/IPAM 和管理 API 不因文档列出就自动接入。新增能力需单独确认工具和范围。
