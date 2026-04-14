---
name: veops-cmdb
description: 用于检查 192.168.130.211:8000 上这套特定的 VEOPS/OneOps CMDB 测试环境。当用户明确提到 VEOPS、OneOps、192.168.130.211 测试站点，或询问该环境里的模型、关系、层级、IPAM、DCIM 时使用。
---

# VEOPS CMDB 测试环境技能

仅面向 `.env` 中配置的这套测试环境。

## 默认行为

- 优先使用随 skill 附带的脚本。
- 除非用户明确询问页面布局、截图或仅能在页面上看到的配置，否则**不要**打开浏览器。
- 除非需要接口名或已整理的场景关系，否则**不要**读取 `references/endpoints.md`。
- 涉及统计分布、可视化、图表时，优先使用 `scripts/analyze_cmdb.py`。
- 除非用户明确要求导出独立页面，否则**不要**生成 `.html` 图表文件；默认直接输出可渲染的 ```echarts 代码块。
- 默认返回精简总结，不返回原始 JSON；只有用户明确要求时才返回原始响应。

## 快速路径

1. 需要鉴权时，先运行一次 `scripts/login.sh`。
2. 按问题选择最小可用脚本：

```bash
tmp/veops-cmdb/scripts/list-models.sh
tmp/veops-cmdb/scripts/model-attributes.sh <type_id>
tmp/veops-cmdb/scripts/model-relations.sh <type_id>
tmp/veops-cmdb/scripts/fetch-json.sh "/api/v0.1/relation_types"
tmp/veops-cmdb/scripts/fetch-json.sh "/api/v0.1/ci/s?q=_type:project&count=20"
tmp/veops-cmdb/scripts/fetch-json.sh "/api/v0.1/ci_relations/s?root_id=<ci_id>&level=1,2,3"
python3 tmp/veops-cmdb/scripts/analyze_cmdb.py --mode summary --output markdown
python3 tmp/veops-cmdb/scripts/analyze_cmdb.py --mode app-relations --output markdown
python3 tmp/veops-cmdb/scripts/analyze_cmdb.py --mode summary --output markdown-echarts-only
```

## 输出风格

- 模型列表类问题：优先输出 `ID / 名称 / 别名 / 唯一键` 表格。
- 单模型问题：只总结关键字段和关键关系。
- 场景类问题：简要说明业务、运行时、IPAM、DCIM 四条链路。
- 图表类问题：优先输出 ECharts；饼图用于分布，占比；柱状图用于目标数量对比。
- 若用户只说“画图 / 渲染图表 / 可视化”，默认返回 Markdown + ```echarts，而不是 HTML 文件路径。

## 备注

- 这套环境中，`project` 对应“应用”模型。
- 凭据必须保留在 `.env` 中。
- 如需图表规范，读取 `references/chart-guide.md` 或 `references/echarts-examples.md`。
