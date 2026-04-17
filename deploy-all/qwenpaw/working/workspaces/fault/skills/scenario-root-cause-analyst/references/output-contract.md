# Output Contract

`scripts/analyze_scenario.py` 默认输出单个 JSON 对象，字段如下：

- `summary`: 面向用户的结论摘要
- `rootCause`: 根因对象，至少包含 `type`，可补充 `object`
- `steps`: 分析步骤数组，元素建议包含 `id`、`status`
- `logEntries`: 过程日志数组，元素建议包含 `stage`、`summary`

示例：

```json
{
  "summary": "已定位为数据库死锁导致 CMDB 新增失败",
  "rootCause": {"type": "数据库异常", "object": "cmdb_device"},
  "steps": [{"id": "database-analysis", "status": "success"}],
  "logEntries": [{"stage": "database-analysis", "summary": "捕获锁等待"}]
}
```
