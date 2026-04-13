# `echarts` 返回协议模板

Portal 前端会把如下 fenced code block 直接交给 ECharts 渲染：

````markdown
```echarts
{
  "__mockStream": {
    "enabled": true,
    "intervalMs": 300,
    "batchSize": 2,
    "initialVisiblePoints": 8,
    "totalPoints": 24
  },
  "title": {
    "text": "业务恢复趋势"
  },
  "tooltip": {
    "trigger": "axis"
  },
  "xAxis": {
    "type": "category",
    "boundaryGap": false,
    "data": ["", "", "", "", "", "", "", ""]
  },
  "yAxis": {
    "type": "value"
  },
  "series": [
    {
      "name": "主指标",
      "type": "line",
      "smooth": true,
      "data": [8200, 8100, 7900, 7600, 7200, 620, 540, 510]
    }
  ]
}
```
````

推荐字段：

- `__mockStream.enabled`
  - 是否启用前端渐进播放
- `__mockStream.intervalMs`
  - 每轮追加间隔，演示建议 `200~500`
- `__mockStream.batchSize`
  - 每轮追加几个点，建议 `1~3`
- `__mockStream.initialVisiblePoints`
  - 首屏先展示的点位数，避免空白等待
- `__mockStream.totalPoints`
  - 全量点位数

推荐实践：

- 首屏不要只给 1-2 个点，否则像“图没出来”
- 如果是演示态 mock，不要把播放窗口做成分钟级
- 图表应优先表达“故障前 -> 处置点 -> 恢复后”的趋势对比
- 高价值事件建议用 `markPoint` 或 `markLine` 标记，例如故障发生、执行处置
