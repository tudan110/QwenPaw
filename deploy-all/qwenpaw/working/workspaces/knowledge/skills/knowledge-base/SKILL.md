---
name: knowledge-base
description: 运维知识库能力。用于知识资料上传入库、手动沉淀、资料管理、关键词/向量混合检索、基于检索证据回答知识问题。用户询问知识库、SOP、历史案例、最佳实践、故障经验、资料检索、文档上传或知识沉淀时使用。
---

# Knowledge Base

这是知识专员的主知识库能力，替代旧 demo `rag-skill`。

## 使用边界

- 默认只服务 `knowledge` 智能体，不作为 gateway 的全局隐式检索中间件。
- 其他智能体需要 SOP、历史案例、最佳实践、故障经验时，应协同 `knowledge`，由 `knowledge` 使用本 skill 检索。
- 不要在普通查询、实时告警、工单列表、CMDB 状态查询前自动检索知识库。

## 数据与配置

- 这是内嵌到 QwenPaw extension / skill 的知识库引擎，不需要单独部署原项目服务，也不通过反向代理嫁接。
- 数据默认存放在本 skill 的 `data/` 目录；容器部署可设置 `KNOWLEDGE_BASE_DATA_DIR` 或 `QWENPAW_KNOWLEDGE_BASE_DATA_DIR` 到 PVC 路径。
- `DEEPSEEK_API_KEY` 保留用于插件自带 RAG 合成和兜底。
- `DASHSCOPE_API_KEY` 保留用于向量检索；可通过管理接口开关 embedding。
- 知识专员对话中，优先使用当前 QwenPaw 模型基于检索证据组织最终回答。

## 常用命令

先进入本 skill 目录：

```bash
cd skills/knowledge-base
```

健康检查：

```bash
python3 scripts/knowledge_base_cli.py health
```

检索：

```bash
python3 scripts/knowledge_base_cli.py query "数据库慢查询怎么处置"
```

手动沉淀：

```bash
python3 scripts/knowledge_base_cli.py manual-entry --title "慢查询处置原则" --content "..."
```

上传文件：

```bash
python3 scripts/knowledge_base_cli.py ingest /path/to/file.md
```

资料列表：

```bash
python3 scripts/knowledge_base_cli.py sources
```

## 回答要求

- 先检索，再回答；不要凭空编造知识库中不存在的结论。
- 回答中说明命中的来源文件、标题或 locator。
- 如果没有命中，明确说明“当前知识库未找到匹配资料”，再给出可选的通用建议或让用户补充资料。
