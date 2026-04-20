---
name: veops-cmdb
description: 用于查询当前 `.env` 配置所指向的 VEOPS CMDB 环境。当用户询问模型、关系、层级、IPAM、DCIM、应用拓扑、资源拓扑或需要按应用/资源展开 CMDB 关系时使用。
---

# VEOPS CMDB 查询技能

仅面向 `.env` 中配置的当前 CMDB 环境。
`.env.example` 只是模板示例，运行时实际读取的是 `.env`。

不要在对外描述里写死某个固定地址、某套“测试环境”或特定站点；环境信息应完全来自 `.env`。

## 默认行为

- 优先使用随 skill 附带的脚本。
- 即使 agent 具备 `browser_use` 或其他浏览器相关工具，处理本 skill 的 CMDB 查询时也**禁止**使用它们；只允许后台脚本、HTTP 请求、curl、Python 标准库/HTTP 客户端这类无界面方式。
- 除非用户明确询问页面布局、截图或仅能在页面上看到的配置，否则**不要**打开浏览器。
- 除非需要接口名或已整理的场景关系，否则**不要**读取 `references/endpoints.md`。
- 涉及统计分布、目标数量对比类图表时，优先使用 `scripts/veops-cmdb.sh analyze ...`。
- 涉及具体应用的关系拓扑，先运行 `scripts/veops-cmdb.sh find-project <应用名>` 解析目标应用；唯一命中后直接使用 `scripts/veops-cmdb.sh app-topology <应用名>` 输出标准 ECharts `series` 结构，不要手写拓扑 option。
- 如果用户没有明确指定应用名，且当前系统里存在多个应用，**不要默认任选一个**。必须先列出候选应用名并请用户明确指定。
- 当用户要求展示某个应用的关系拓扑图时，默认使用 ECharts `series.type = 'tree'`，并设置为从左到右展开；根节点使用 CMDB 中实际应用名。
- 除非用户明确要求导出独立页面，否则**不要**生成 `.html` 图表文件；默认直接输出可渲染的 ```echarts 代码块。
- 默认返回精简总结，不返回原始 JSON；只有用户明确要求时才返回原始响应。

## 快速路径

1. 统一主入口是 `scripts/veops-cmdb.sh`。
2. 需要鉴权时，先运行一次 `scripts/veops-cmdb.sh login`。
   它现在走后台 HTTP 会话，不会再打开桌面浏览器。
3. 按问题选择最小可用命令：

```bash
scripts/veops-cmdb.sh find-project <应用名>
scripts/veops-cmdb.sh app-topology <应用名>
scripts/veops-cmdb.sh list-models
scripts/veops-cmdb.sh model-attributes <type_id>
scripts/veops-cmdb.sh model-relations <type_id>
scripts/veops-cmdb.sh fetch "/api/v0.1/relation_types"
scripts/veops-cmdb.sh fetch "/api/v0.1/ci/s?q=_type:project&count=20"
scripts/veops-cmdb.sh fetch "/api/v0.1/ci_relations/s?root_id=<ci_id>&level=1,2,3&count=10000"
scripts/veops-cmdb.sh analyze --mode summary --output markdown
scripts/veops-cmdb.sh analyze --mode app-relations --output markdown
scripts/veops-cmdb.sh analyze --mode summary --output markdown-echarts-only
```

## 输出风格

- 模型列表类问题：优先输出 `ID / 名称 / 别名 / 唯一键` 表格。
- 单模型问题：只总结关键字段和关键关系。
- 场景类问题：简要说明业务、运行时、IPAM、DCIM 四条链路。
- 图表类问题：优先输出 ECharts；饼图用于分布，占比；柱状图用于目标数量对比。
- 关系拓扑类问题：优先输出从左到右树状图；根节点放应用，向右展开产品归属、运行时、中间件、数据库、IPAM、DCIM 等关系链。
- 若用户要“某个应用的关系拓扑 / 拓扑图 / 架构关系图”，先用 `find-project` 明确目标应用；只有在唯一命中时才运行 `app-topology`，并直接返回它生成的标准 ```echarts 代码块，不要自己重写成简写结构。
- 若当前存在多个应用而用户没有给出明确应用名，先回复候选应用名让用户选择，不要默认返回任意一个应用的拓扑。
- 若用户只说“画图 / 渲染图表 / 可视化”，默认返回 Markdown + ```echarts，而不是 HTML 文件路径。
- 面向最终用户的回复、标题、摘要、图表标题中，不要出现 `VEOPS`、`veops`、`OneOps` 等产品字样，除非用户明确要求保留这些名称。

## 备注

- 这套环境中，`project` 对应“应用”模型。
- 凭据必须保留在 `.env` 中。
- 如需图表规范，读取 `references/chart-guide.md` 或 `references/echarts-examples.md`。
- 如果用户要做资源导入、资源纳管、批量导入，改用同级 `veops-cmdb-import` skill。
