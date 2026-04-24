---
name: inspection-analyst
category: inspection
tags: [inspection, health-check, cmdb, topology, metrics, database, middleware, resource]
triggers: [巡检, 资源巡检, 健康检查, 数据库巡检, 帮我巡检一下数据库, 帮我巡检一下中间件]
description: 面向 inspection 智能体的资源巡检技能。先协作 query 智能体使用 veops-cmdb 明确巡检对象的拓扑、resId/CI ID 与 ciType，再查询该资源类型的全部指标定义与指标值，最后向用户展示巡检结果。
---

# Inspection Analyst

该技能用于处理“帮我巡检一下数据库 / 中间件 / 某个资源”的场景。

它的目标不是只输出一句“可以巡检”，而是完成一条真实巡检链路：

1. 先识别用户要巡检的对象
2. 协作 query 智能体使用 `veops-cmdb` 确认拓扑、资源 ID（CI ID / resId）与资源类型（`ciType` / `metricType`）
3. 调用指标定义接口，提取该资源类型的全部指标编码
4. 调用指标数据接口，使用 `resId + 全部指标编码数组` 获取巡检指标数据
5. 把拓扑确认结果与指标数据整理成用户可读的巡检结果

---

## 一、何时使用

当用户请求满足以下特征时，优先使用本技能：

- 用户明确要“巡检 / 健康检查 / 查看指标”
- 用户给出了一个资源对象、资源名称、数据库、中间件、主机、应用实例等巡检目标
- 用户希望看到实际指标结果，而不是巡检方案

典型触发语句：

- `帮我巡检一下数据库`
- `帮我巡检一下 mysql`
- `帮我看一下这个中间件的指标`
- `对这个资源做健康检查`

---

## 二、执行原则

### 1. 先真实执行，再组织说明

如果当前工作区具备可用工具，就必须优先执行真实动作：

1. 优先使用内置工具 `chat_with_agent` 协作 `query` 智能体
2. 让 `query` 智能体使用 `veops-cmdb` 明确：
   - 根资源名称
   - `resId / CI ID`
   - `ciType`
   - 基本拓扑关系
3. 一旦拿到 `resId` 与 `ciType`，立即执行：

```bash
cd skills/inspection-analyst && python scripts/inspect_resource_metrics.py --res-id <CI_ID> --metric-type <ciType> --inspection-object "<用户巡检对象>" --resource-name "<CMDB确认的资源名>" --output markdown
```

不要停在“计划调用”“下一步执行”“是否继续”。

### 2. 不能猜测 resId / ciType

如果 `query` 智能体返回多个候选资源，不能默认任选一个继续巡检。

此时应明确告诉用户：

- 当前存在多个候选资源
- 每个候选资源的名称 / `resId` / `ciType`
- 请用户指定后再继续

### 3. 默认巡检输出必须包含指标结果

完成巡检后，用户可见输出至少要包含：

1. 巡检对象
2. CMDB 确认的资源信息（资源名、`resId/CI ID`、`ciType`）
3. 拓扑确认摘要
4. 指标定义数量 / 实际采集数量
5. 指标数据表
6. 巡检结论

---

## 三、跨智能体协作要求

涉及 CMDB / 拓扑确认时，必须优先使用 `chat_with_agent` 协作 `query` 智能体，不要只凭用户一句“数据库”就直接假定资源。

推荐协作提示：

```text
请使用 veops-cmdb 帮我确认巡检对象“<用户巡检对象>”在 CMDB 中对应的资源信息，返回：
1. 最匹配的根资源名称
2. resId / CI ID
3. ciType
4. 简要拓扑摘要
5. 如果存在多个候选资源，列出候选清单，不要默认任选一个
```

---

## 四、指标接口配置

该技能固定读取自己目录下的 `.env`，不要回退到别的技能目录。

最小配置：

```bash
INOE_API_BASE_URL=http://192.168.130.51:30080
INOE_API_TOKEN=your_jwt_token_here
INSPECTION_METRIC_TIMEOUT_SECONDS=120
INSPECTION_METRIC_PAGE_SIZE=100
INSPECTION_NOTIFY_WEBHOOK_URL=
INSPECTION_NOTIFY_DINGTALK_WEBHOOK_URL=
INSPECTION_NOTIFY_DINGTALK_SECRET=
INSPECTION_NOTIFY_DINGTALK_KEYWORD=
INSPECTION_NOTIFY_FEISHU_WEBHOOK_URL=
INSPECTION_NOTIFY_FEISHU_SECRET=
INSPECTION_NOTIFY_TIMEOUT_SECONDS=8
INSPECTION_NOTIFY_MENTION_ALL=true
```

规则：

- 必须使用 `INOE_API_BASE_URL` 与 `INOE_API_TOKEN`
- `getMetricDefinitions` 与 `getMetricData` 共用同一个 base URL
- 缺少 token 时，必须明确报错，不能假装查询成功
- `INSPECTION_NOTIFY_WEBHOOK_URL` 是通用应用 webhook，可对接量子密信
- 支持按配置同时推送到：应用（可配置为量子密信）、钉钉、飞书
- 如果未配置任何 webhook，必须明确体现“通知未配置”

---

## 五、巡检脚本能力

本技能目录下的 `scripts/inspect_resource_metrics.py` 负责：

1. 查询全部指标定义
2. 提取全部指标编码
3. 调用 `/resource/pm/getMetricData`
4. 使用 `resId + queryKeys=[全部指标编码]` 一次性查询指标数据
5. 在 webhook 已配置时，自动把巡检结果推送到应用（可配置为量子密信）、钉钉、飞书
6. 输出 Markdown / JSON 结果

常用方式：

```bash
cd skills/inspection-analyst
python scripts/inspect_resource_metrics.py \
  --res-id 3094 \
  --metric-type mysql \
  --inspection-object "数据库" \
  --resource-name "db_mysql_001" \
  --output markdown
```

---

## 六、最终输出要求

最终回复要以巡检结果为主，不要输出 alarm-analyst 那种工单、告警闭环、清警等内容。

建议结构：

```markdown
## 巡检结果
- 巡检对象：...
- 资源名称：...
- 资源 ID（CI ID）：...
- 资源类型：...
- 指标总数：...
- 数据来源：...
- 通知状态：...

## 拓扑确认
- ...

## 指标数据
| 指标名 | 指标编码 | 最近值 | 采样时间 | Min/Avg/Max | 数据来源 |
|---|---|---|---|---|---|

## 巡检结论
- ...
```

用户可见输出要直接解释资源状态，不要只贴原始 JSON。

---

## 七、通知要求

巡检结果生成后，必须执行通知推送：

1. 通知由 `scripts/inspect_resource_metrics.py` 内部自动完成
2. 可按 `.env` 配置同时推送到：
   - 应用 webhook（可配置为量子密信）
   - 钉钉
   - 飞书
3. 推送内容必须体现这是 **AI 巡检结果**
4. 至少包含：
   - 巡检对象
   - 资源名称
   - 资源 ID（CI ID）
   - 资源类型
   - 指标总数
   - 巡检时间
5. 如果未配置任何 webhook，必须明确写出“通知未配置”
6. 如果部分渠道推送失败，必须明确写出“部分通知发送失败”
