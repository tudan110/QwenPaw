# `portal-action` 返回协议模板

Portal 前端会识别如下 fenced code block：

````markdown
```portal-action
{
  "id": "restart-instance-wo-20260402-001",
  "type": "restart-instance",
  "title": "建议执行：重启异常实例",
  "summary": "实例线程数长期卡满，建议先重启实例释放资源后继续观察。",
  "status": "ready",
  "riskLevel": "medium",
  "sourceWorkorderNo": "WO-20260402-001",
  "targetName": "app-service-01",
  "targetIp": "10.10.10.12"
}
```
````

字段约定：

- `id`
  - 当前动作唯一标识
- `type`
  - 动作类型，建议稳定命名
- `title`
  - 前端按钮和确认框主标题
- `summary`
  - 动作意图说明
- `status`
  - `ready | running | success | failed`
- `riskLevel`
  - `low | medium | high`
- 其他字段
  - 作为后续执行动作时的上下文参数透传

建议：

- 动作参数尽量扁平，避免嵌套过深
- 高风险动作必须保留足够的设备、工单、目标对象标识
- Portal 点击动作按钮后，应该把整个对象作为下一轮聊天上下文的一部分回传
