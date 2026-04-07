---
name: {{skill-name}}
category: {{business-category}}
tags: [{{tag-1}}, {{tag-2}}, {{tag-3}}]
triggers: [{{trigger-1}}, {{trigger-2}}, {{trigger-3}}]
description: 面向 {{business-scene}} 的技能。适用于上游已经整理好结构化上下文，并希望在当前 CoPAW 聊天会话中完成分析、建议、动作执行和结果验证的场景。
---

# {{Skill Display Name}}

该技能用于处理“{{business-scene}}”场景。

目标：

- 在当前 CoPAW 聊天会话中完成业务分析
- 基于结构化上下文路由到合适 playbook
- 返回适合 Portal 直接渲染的 markdown、`portal-action`、`echarts`

## 何时使用

- 用户消息中已经带有结构化上下文
- 用户目标是继续推进业务闭环，而不是只做查询
- 当前场景存在明确的动作建议或恢复验证需求

## 何时不要使用

- 用户只是做列表查询、统计查询、详情查询
- 用户没有给足上下文，且当前 skill 无法自行补齐

## 输入协议

建议使用如下输入模式：

1. 用户消息中包含 `【业务上下文(JSON)】`
2. Skill 从消息中提取 JSON，写入临时文件
3. 调用标准桥接脚本：

```bash
python scripts/chat_skill_bridge.py diagnose --context-file /tmp/business_context.json
```

如用户明确确认动作：

```bash
python scripts/chat_skill_bridge.py execute --context-file /tmp/business_context.json
```

## 架构说明

推荐链路：

1. 当前 CoPAW 聊天收到用户请求
2. 命中 `{{skill-name}}`
3. `scripts/chat_skill_bridge.py`
4. `runtime/router.py`
5. `runtime/playbooks/<business_flow>.py`
6. `runtime/tool_adapters.py`
7. 输出 markdown / `portal-action` / `echarts`

## 扩展约定

- 新场景优先在 `runtime/playbooks/` 新增 playbook
- 新外部能力优先封装到 `runtime/tool_adapters.py` 或 `src/copaw/extensions/integrations/*`
- 不要让 Portal 直接执行业务脚本
- 不要在 skill 内另起 CoPAW 子会话

## 输出要求

- 先给分析结论
- 再给证据或过程块
- 如存在下一步动作，输出 `portal-action`
- 如存在结构化趋势或指标结果，输出 `echarts`
