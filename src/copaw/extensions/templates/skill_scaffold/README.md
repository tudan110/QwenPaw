# Skill Scaffold

把这套目录复制到：

`src/copaw/agents/skills/<your-skill-name>/`

推荐目录结构：

```text
<your-skill-name>/
  SKILL.md
  scripts/
    chat_skill_bridge.py
  runtime/
    __init__.py
    models.py
    router.py
    tool_adapters.py
    reasoners.py
    playbooks/
      __init__.py
      base.py
      <business_flow>.py
```

职责分层：

- `SKILL.md`
  - 定义 skill 触发条件、输入协议、输出约束
- `scripts/chat_skill_bridge.py`
  - Skill 在 CoPAW 聊天中的标准入口
- `runtime/router.py`
  - 根据上下文选择具体业务场景
- `runtime/playbooks/*.py`
  - 单个业务流程的轻量编排
- `runtime/tool_adapters.py`
  - 对外部接口、MCP、平台资源做统一封装
- `runtime/reasoners.py`
  - 负责把业务结果组织成 markdown / portal-action / echarts

建议的长期约束：

- 不要把业务编排重新下沉回 Portal
- 不要在 skill 内额外创建 CoPAW 子会话
- 高风险动作优先走“模型判断 + 确定性工具执行”的组合，而不是纯自由生成
