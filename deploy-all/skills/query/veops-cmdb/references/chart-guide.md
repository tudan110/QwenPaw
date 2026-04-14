# 图表使用指南

本技能支持用 ECharts 渲染 CMDB 统计图。默认优先返回 Markdown；只有用户明确要图表或页面直渲染时，再输出 ECharts 代码块。

## 规则

- 优先使用 ECharts
- 不生成 PNG 等图片文件
- 图表必须能直接放进 ```echarts 代码块渲染
- 一次回复通常 1~3 个图表就够了
- 先给一句结论，再给图表
- 除非用户明确要求“导出 HTML 页面”或“保存为文件”，否则不要生成独立 `.html` 文件
- 默认把图表直接写在回复里，而不是返回工作区文件路径

## 推荐图表

| 场景 | 推荐图表 |
|---|---|
| 模型分组分布 | 饼图 |
| 关系类型分布 | 环形图 |
| 应用关联目标分布 | 柱状图 |
| 只想给前端喂图表 | 只输出 ```echarts 代码块 |

## 调用方式

```bash
python3 tmp/veops-cmdb/scripts/analyze_cmdb.py --mode summary --output markdown
python3 tmp/veops-cmdb/scripts/analyze_cmdb.py --mode model-groups --output markdown
python3 tmp/veops-cmdb/scripts/analyze_cmdb.py --mode relation-types --output markdown
python3 tmp/veops-cmdb/scripts/analyze_cmdb.py --mode app-relations --output markdown
python3 tmp/veops-cmdb/scripts/analyze_cmdb.py --mode summary --output markdown-echarts-only
```

## 模式说明

- `summary`：模型分组、关系类型、应用关联目标三类总览
- `model-groups`：模型分组统计
- `relation-types`：关系类型统计
- `app-relations`：应用模型 `project` 的入向/出向关系与目标分布
