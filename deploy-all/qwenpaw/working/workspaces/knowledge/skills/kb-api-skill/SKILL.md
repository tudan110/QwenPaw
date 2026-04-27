---
name: kb-api-skill
category: knowledge
tags: [knowledge, kb, rag, retrieval, qa]
triggers: [知识库, 知识查询, 查资料, 检索, 文档查找, 运维知识, SOP, 故障案例, 最佳实践]
description: 知识专员用来检索 qwenpaw 内置知识库子系统（/api/portal/knowledge/*）。命中证据时按 6 段契约整理 markdown 答复并附引用；未命中时明确"知识库无相关资料"，必要时再选择 LLM 兜底。回答必须基于检索结果，禁止凭空编造。
---

# Knowledge Base API Skill（知识库检索技能）

知识专员调本技能从知识库子系统拉证据回答问题。子系统 = qwenpaw 同进程内的 `/api/portal/knowledge/*`，由 `extensions/knowledge_kb` 提供，存储在 `$QWENPAW_WORKING_DIR/knowledge_kb/`。

## 何时使用

**应该用**：
- 用户问运维 SOP / 历史故障案例 / 处置步骤 / 平台知识 / 接口规范 / 术语定义
- gateway 智能体协同转过来的"知识问答"类任务
- 需要带引用的、有边界的回答（不能空口编造）

**不应该用**：
- 用户问"实时告警"——那是 query / fault 智能体的事
- 用户问"创建工单"——那是 order 智能体的事
- 闲聊、代码生成、纯算术——直接回答即可

## 工作流

每次接到知识问答类任务，按下面三步走，**不要跳步**。

### Step 1：检索

用 `execute_shell_command` 调 `scripts/query.sh`：

```bash
bash skills/kb-api-skill/scripts/query.sh "用户的原始问题"
```

可选过滤（按需）：

```bash
bash skills/kb-api-skill/scripts/query.sh "原始问题" \
  --source-scope tenant_private \
  --source-type document
```

返回 JSON 格式的 6 段响应：

```json
{
  "summary": "...",
  "overall_confidence": 0.78,
  "layout_mode": "rich",
  "answer_intent": "...",
  "relevant_evidence": [
    {"id":"...", "title":"...", "excerpt":"...", "confidence_band":"high",
     "source": {"filename":"...", "scope_label":"...", "locator":"..."}}
  ],
  "evidence_boundary_statement": "...",
  "flags": {"insufficient_evidence": false, ...}
}
```

### Step 2：判断证据充分性

- `flags.insufficient_evidence == true` 或 `relevant_evidence == []`：**进入 Step 3 的"无证据"分支**，不要再加工
- `relevant_evidence` 有内容且 `overall_confidence >= 0.62`：**进入 Step 3 的"有证据"分支**

### Step 3：组织答复

#### 有证据分支

按下面的 markdown 格式回复用户。**事实必须严格出自 evidence**，禁止补充资料外的信息：

```
**结论：** {summary}

**依据：**
- {evidence[0].excerpt} [1]
- {evidence[1].excerpt} [2]
...

**引用：**
1. `{filename}` · {locator} · {scope_label}
2. ...

**置信度：** {confidence_band}（{overall_confidence:.0%}）

{evidence_boundary_statement}
```

每条结论末尾用 `[序号]` 标注引用。多条引用可叠加 `[1][3]`。不要写"根据资料..."这类元注释。

#### 无证据分支

明确告诉用户"知识库未命中相关资料"，给出**可执行的下一步**：

```
**当前知识库未命中** "{用户原问题}" 的明确资料。

**可以尝试：**
- 上传相关 SOP / 故障复盘到知识库（管理面板：「知识专员 → 管理知识库」）
- 用更具体的关键词重问（如指定时间、系统、模块）
- 切换到 fault / query 智能体处理实时类问题

如需我基于通用知识给出参考答案（不基于本地资料），请明确说"用通用知识回答"。
```

**只有用户明确要求时**，才用 `scripts/fallback.sh` 走 LLM 兜底——并在答复开头标注"⚠️ 通用知识，非本地资料"。

### 可选：录入新知识

用户在对话中给出了有价值的方法、SOP、故障复盘，且说"记下来"/"沉淀这个"/"录入知识库"时，调：

```bash
bash skills/kb-api-skill/scripts/manual_entry.sh "标题" "完整内容"
```

成功返回 source_record_id。告诉用户已沉淀到 `runtime_curated` scope，下次相关查询能命中。

## 边界与禁忌

- ❌ **不要**绕过检索直接答——所有知识问答必须先 Step 1
- ❌ **不要**编造"根据知识库"等元注释包装实际是 LLM 编的内容
- ❌ **不要**在 evidence 不足时硬答；明确"未命中"是合格答案
- ❌ **不要**调用 `query` / `fault` / `order` 等其他智能体——你的本职就是知识检索，结果直接回 gateway
- ✅ **要**保留原始引用（filename + locator）让用户能溯源
- ✅ **要**让 confidence_band 透明（高/中/低，对应 high/medium/low）
- ✅ **要**保持简洁——结论先行，列表代替段落
