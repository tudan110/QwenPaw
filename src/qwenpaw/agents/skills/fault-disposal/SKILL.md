---
name: fault-disposal
category: root-cause
tags: [fault, root-cause, diagnosis, ticket, playbook, disposal]
triggers: [故障处置, 工单处置, 根因定位, 处置建议, 影响范围, 故障原因, 恢复验证]
description: 面向工单驱动故障处置的技能。适用于 Portal 或上游系统已经整理好工单上下文，并希望在当前 CoPAW 聊天会话中完成根因分析、处置建议、动作执行和恢复验证的场景。仅当用户意图是“基于工单上下文推进故障处置闭环”时使用；如果用户只是查询实时告警列表、告警统计、告警分布或告警详情，应使用 real-alarm，而不是本技能。
---

# Fault Disposal

该技能用于处理“上游已经形成工单上下文，接下来要做根因定位、处置执行和恢复验证”的场景。

它不是实时告警列表查询技能，也不是通用报表技能。它的目标是基于用户提供的工单上下文，调用 skill 内的诊断/执行脚本补齐证据与处置结果，并在当前聊天会话中完成闭环。

## 何时使用

当用户请求满足以下特征时，优先使用本技能：

- 用户消息中已经带有 `entryWorkorder`、`workorders`、`tags` 等结构化工单上下文
- 目标是“根因定位”“故障处置”“动作执行”“恢复验证”“复盘输出”
- 希望按特定故障类型自动路由到现有 playbook，而不是手工拼分析流程
- 希望继续留在当前 CoPAW 聊天会话，不要另外创建子会话

典型示例：

- `基于当前告警工单继续做故障处置`
- `对这批关联工单执行诊断并给出处置建议`
- `根据工单上下文继续恢复验证`
- `执行建议动作`

## 何时不要使用

如果用户只是想查看告警系统中的实时数据，而不是做故障处置，不要使用本技能。以下场景应交给 `real-alarm`：

- 查询实时告警列表
- 统计告警数量、级别、分布、趋势
- 查看告警详情、活跃告警、严重告警
- 按设备、时间、地区、类型筛选告警

简化判断：

- “查告警” -> `real-alarm`
- “基于工单上下文推进故障处置” -> `fault-disposal`

## 输入方式

本技能优先走“当前聊天会话内的标准 skill 调度”，不要在 skill 内再起 CoPAW 子会话。

当用户消息中带有 `【工单上下文(JSON)】` 代码块时，按以下方式执行：

1. 从用户消息中提取 JSON，原样写入一个临时文件，例如 `/tmp/fault_workorder_context.json`
2. 执行诊断命令：

```bash
cd skills/fault-disposal && python scripts/chat_skill_bridge.py diagnose --context-file /tmp/fault_workorder_context.json
```

3. 读取脚本输出，并在当前聊天会话中直接面向用户回复

如果用户明确确认执行建议动作，则继续：

```bash
cd skills/fault-disposal && python scripts/chat_skill_bridge.py execute --context-file /tmp/fault_workorder_context.json
```

当前主实现仍保留在 skill 内：

- 标准聊天入口：`scripts/chat_skill_bridge.py`
- 兼容旧桥接入口：`scripts/run_ticket_driven_fault_disposal.py`
- 应用层：`runtime/app.py`
- 路由层：`runtime/router.py`
- Playbook：`runtime/playbooks/`
- 工具层：`runtime/tool_adapters.py`
- 模板渲染：`runtime/reasoners.py`

## 架构说明

当前推荐调用链如下：

1. 当前 CoPAW 聊天会话收到用户请求
2. 触发 `fault-disposal` skill
3. `scripts/chat_skill_bridge.py`
4. `runtime/router.py`
5. `runtime/playbooks/<playbook>.py`
6. `runtime/tool_adapters.py`
7. 在当前聊天会话中由外层 CoPAW agent 组织最终答复

执行时必须注意当前工作目录通常是 workspace 根目录，因此脚本命令必须显式进入 `skills/fault-disposal/` 后再执行，不能假设 `scripts/` 位于 workspace 根目录。

## 默认处理流程

脚本会按以下顺序组织故障处置流程：

1. 接收 `entryWorkorder/workorders/tags/alarmCode/source/sessionId`
2. 构建 `TicketContext`
3. 通过 `router.py` 选择最适合的 playbook
4. playbook 调用工具层补齐关联工单、根因候选、应用/数据库观测等上下文
5. 标准聊天会话中的 CoPAW agent 基于脚本结果生成面向用户的回答
6. 如用户确认动作，再调用 `execute` 完成处置和恢复验证

## 输出重点

优先关注这些输出：

- 诊断结论
- 关键证据
- 建议动作
- 恢复验证
- `portal-action` 代码块
- `echarts` 代码块

## 扩展约定

后续新增故障类型时，优先按以下方式扩展：

- 在 `runtime/playbooks/` 下新增 playbook
- 在 `runtime/router.py` 中补充路由规则
- 在 `runtime/tool_adapters.py` 中补充领域工具封装
- 在 `scripts/chat_skill_bridge.py` 中补充面向标准聊天会话的输出适配

不要把领域编排重新下沉回 Portal 页面层，也不要在 skill 内再额外创建 CoPAW 子会话。

## 配置说明

本技能现在既承载故障处置的主编排代码，也承载标准聊天会话下的脚本入口。

其中部分能力会复用 CoPAW 包内的扩展集成资源，例如：

- `src/qwenpaw/extensions/integrations/alarm_workorders/query_alarm_workorders.py`

这类依赖仍属于公共接入资源，不属于 Portal 页面逻辑。

如果 skill 无法定位仓库根目录，可通过环境变量指定：

- `QWENPAW_FAULT_DISPOSAL_PROJECT_ROOT`
- `QWENPAW_PORTAL_PROJECT_ROOT`

如需显式指定告警工单桥接脚本，也可设置：

- `QWENPAW_PORTAL_ALARM_WORKORDERS_SCRIPT`

## 执行要求

- 先跑真实脚本，不要只输出“建议执行某命令”
- 优先使用用户消息里的工单上下文 JSON，不再接受告警文本直驱
- 不要再在 skill 内额外走 `/api/chats` 或 `/console/chat` 创建子会话
- 如果脚本已经输出适合展示的 markdown，请尽量保留原样，尤其不要丢掉 `portal-action` 和 `echarts` 代码块
- 如果用户目标是根因定位，返回结果时应围绕“故障点、证据、处置动作、恢复状态”组织内容
- 如果诊断结果存在明确可执行动作，最终回复中必须保留且只保留一个 `portal-action` 代码块；不能只写“请回复执行建议动作”而不附 action
- 对于“终止异常慢 SQL 会话”这类动作，优先直接保留脚本输出中的 `portal-action` 原文，不要改写字段名、不要删减 JSON 字段
- 如果模型准备自行整理自然语言总结，也必须在最终总结末尾补回 `portal-action` 代码块；缺少 `portal-action` 视为不完整回复
