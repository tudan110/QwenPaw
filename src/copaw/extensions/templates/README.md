# CoPAW Extension Templates

这组模板用于后续新增“数字员工业务流程”时的统一起手结构。

设计原则：

- Skill 继续放在 `src/copaw/agents/skills/<skill-name>/`
- 外部系统接入继续放在 `src/copaw/extensions/integrations/`
- Portal 只负责前端展示，不再编排业务流程
- 所有业务交互统一沉淀到 CoPAW 聊天会话

建议的新流程开发顺序：

1. 先复制 `skill_scaffold/`，生成新的 skill 目录
2. 修改 `SKILL.template.md`，明确触发条件、输入协议、执行要求
3. 按业务场景补 `runtime/router.py` 和 `runtime/playbooks/*.py`
4. 把外部接口包装进 `runtime/tool_adapters.py` 或 `src/copaw/extensions/integrations/*`
5. 输出 `portal-action` / `echarts` 时，遵循 `protocols/` 下的协议模板

模板目录说明：

- `skill_scaffold/`
  - 新 skill 的目录骨架和核心代码模板
- `protocols/`
  - Portal 前端消费的返回协议模板
